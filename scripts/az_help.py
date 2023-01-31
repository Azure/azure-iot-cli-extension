# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import argparse

from azure.cli.core.commands import ExtensionCommandSource

from knack.help import (HelpFile as KnackHelpFile, CommandHelpFile as KnackCommandHelpFile,
                        GroupHelpFile as KnackGroupHelpFile, ArgumentGroupRegistry as KnackArgumentGroupRegistry,
                        HelpExample as KnackHelpExample, HelpParameter as KnackHelpParameter,
                        _print_indent, CLIHelp, HelpAuthoringException)
from azure.cli.core._help import CliHelpFile, CliGroupHelpFile, CliCommandHelpFile, ArgumentGroupRegistry, HelpExample, HelpParameter

from knack.log import get_logger
from knack.util import CLIError

logger = get_logger(__name__)

PRIVACY_STATEMENT = """
Welcome to Azure CLI!
---------------------
Use `az -h` to see available commands or go to https://aka.ms/cli.

Telemetry
---------
The Azure CLI collects usage data in order to improve your experience.
The data is anonymous and does not include commandline argument values.
The data is collected by Microsoft.

You can change your telemetry settings with `az configure`.
"""

WELCOME_MESSAGE = r"""
     /\
    /  \    _____   _ _  ___ _
   / /\ \  |_  / | | | \'__/ _\
  / ____ \  / /| |_| | | |  __/
 /_/    \_\/___|\__,_|_|  \___|


Welcome to the cool new Azure CLI!

Use `az --version` to display the current version.
Here are the base commands:
"""


# PrintMixin class to decouple printing functionality from AZCLIHelp class.
# Most of these methods override print methods in CLIHelp
class CLIPrintMixin(CLIHelp):
    def _print_header(self, cli_name, help_file):
        super(CLIPrintMixin, self)._print_header(cli_name, help_file)

        links = help_file.links
        if links:
            link_text = "{} and {}".format(", ".join([link["url"] for link in links[0:-1]]),
                                           links[-1]["url"]) if len(links) > 1 else links[0]["url"]
            link_text = "For more information, see: {}\n".format(link_text)
            _print_indent(link_text, 2, width=self.textwrap_width)

    def _print_detailed_help(self, cli_name, help_file):
        CLIPrintMixin._print_extensions_msg(help_file)
        super(CLIPrintMixin, self)._print_detailed_help(cli_name, help_file)
        self._print_az_find_message(help_file.command)

    @staticmethod
    def _get_choices_defaults_sources_str(p):
        choice_str = '  Allowed values: {}.'.format(', '.join(sorted([str(x) for x in p.choices]))) \
            if p.choices else ''
        default_value_source = p.default_value_source if p.default_value_source else 'Default'
        default_str = '  {}: {}.'.format(default_value_source, p.default) \
            if p.default and p.default != argparse.SUPPRESS else ''
        value_sources_str = CLIPrintMixin._process_value_sources(p) if p.value_sources else ''
        return '{}{}{}'.format(choice_str, default_str, value_sources_str)

    @staticmethod
    def _print_examples(help_file):
        indent = 0
        _print_indent('Examples', indent)
        for e in help_file.examples:
            indent = 1
            _print_indent('{0}'.format(e.short_summary), indent)
            indent = 2
            if e.long_summary:
                _print_indent('{0}'.format(e.long_summary), indent)
            _print_indent('{0}'.format(e.command), indent)
            print('')

    @staticmethod
    def _print_az_find_message(command):
        indent = 0
        message = 'To search AI knowledge base for examples, use: az find "az {}"'.format(command)
        _print_indent(message + '\n', indent)

    @staticmethod
    def _process_value_sources(p):
        commands, strings, urls = [], [], []

        for item in p.value_sources:
            if "string" in item:
                strings.append(item["string"])
            elif "link" in item and "command" in item["link"]:
                commands.append(item["link"]["command"])
            elif "link" in item and "url" in item["link"]:
                urls.append(item["link"]["url"])

        command_str = '  Values from: {}.'.format(", ".join(commands)) if commands else ''
        string_str = '  {}'.format(", ".join(strings)) if strings else ''
        string_str = string_str + "." if string_str and not string_str.endswith(".") else string_str
        urls_str = '  For more info, go to: {}.'.format(", ".join(urls)) if urls else ''
        return '{}{}{}'.format(command_str, string_str, urls_str)

    @staticmethod
    def _print_extensions_msg(help_file):
        if help_file.type != 'command':
            return
        if isinstance(help_file.command_source, ExtensionCommandSource):
            logger.warning(help_file.command_source.get_command_warn_msg())

            # Extension preview/experimental warning is disabled because it can be confusing when displayed together
            # with command or command group preview/experimental warning. See #12556

            # # If experimental is true, it overrides preview
            # if help_file.command_source.experimental:
            #     logger.warning(help_file.command_source.get_experimental_warn_msg())
            # elif help_file.command_source.preview:
            #     logger.warning(help_file.command_source.get_preview_warn_msg())


class AzCliHelp(CLIPrintMixin, CLIHelp):

    def __init__(self, cli_ctx):
        super(AzCliHelp, self).__init__(cli_ctx,
                                        privacy_statement=PRIVACY_STATEMENT,
                                        welcome_message=WELCOME_MESSAGE,
                                        command_help_cls=CliCommandHelpFile,
                                        group_help_cls=CliGroupHelpFile,
                                        help_cls=CliHelpFile)
        from knack.help import HelpObject

        # TODO: This workaround is used to avoid a bizarre bug in Python 2.7. It
        # essentially reassigns Knack's HelpObject._normalize_text implementation
        # with an identical implemenation in Az. For whatever reason, this fixes
        # the bug in Python 2.7.
        @staticmethod
        def new_normalize_text(s):
            if not s or len(s) < 2:
                return s or ''
            s = s.strip()
            initial_upper = s[0].upper() + s[1:]
            trailing_period = '' if s[-1] in '.!?' else '.'
            return initial_upper + trailing_period

        HelpObject._normalize_text = new_normalize_text  # pylint: disable=protected-access

        self._register_help_loaders()
        self._name_to_content = {}

    def show_help(self, cli_name, nouns, parser, is_group):
        self.update_loaders_with_help_file_contents(nouns)

        delimiters = ' '.join(nouns)
        help_file = self.command_help_cls(self, delimiters, parser) if not is_group \
            else self.group_help_cls(self, delimiters, parser)
        help_file.load(parser)
        if not nouns:
            help_file.command = ''
        else:
            AzCliHelp.update_examples(help_file)
        # import pdb; pdb.set_trace()
        flattened_helps = []
        to_check = [(help_file, parser)]
        while to_check:
            child, child_parser = to_check.pop(0)
            flattened_helps.append(child)
            is_group = hasattr(child, "children")
            help_file = None
            if is_group:
                help_file = self.group_help_cls(self, child.delimiters, child_parser)
                for sub_child in child.children:
                    to_check.append((sub_child, parser.choices[sub_child.name]))
            else:
                help_file = self.command_help_cls(self, child.delimiters, child_parser)

            self._print_detailed_help(cli_name, help_file)

        # self._print_detailed_help(cli_name, help_file)
        # from azure.cli.core.util import show_updates_available
        # show_updates_available(new_line_after=True)

    def get_examples(self, command, parser, is_group):
        """Get examples of a certain command from the help file.
        Get the text of the example, strip the newline character and
        return a list of commands which start with the given command name.
        """
        nouns = command.split(' ')[1:]
        self.update_loaders_with_help_file_contents(nouns)

        delimiters = ' '.join(nouns)
        help_file = self.command_help_cls(self, delimiters, parser) if not is_group \
            else self.group_help_cls(self, delimiters, parser)
        help_file.load(parser)

        def strip_command(command):
            command = command.replace('\\\n', '')
            contents = [item for item in command.split(' ') if item]
            return ' '.join(contents).strip()

        examples = []
        for example in help_file.examples:
            if example.command and example.name:
                examples.append({
                    'command': strip_command(example.command),
                    'description': example.name
                })

        return examples

    def _register_help_loaders(self):
        import azure.cli.core._help_loaders as help_loaders
        import inspect

        def is_loader_cls(cls):
            return inspect.isclass(cls) and cls.__name__ != 'BaseHelpLoader' and issubclass(cls, help_loaders.BaseHelpLoader)  # pylint: disable=line-too-long

        versioned_loaders = {}
        for cls_name, loader_cls in inspect.getmembers(help_loaders, is_loader_cls):
            loader = loader_cls(self)
            versioned_loaders[cls_name] = loader

        if len(versioned_loaders) != len({ldr.version for ldr in versioned_loaders.values()}):
            ldrs_str = " ".join("{}-version:{}".format(cls_name, ldr.version) for cls_name, ldr in versioned_loaders.items())  # pylint: disable=line-too-long
            raise CLIError("Two loaders have the same version. Loaders:\n\t{}".format(ldrs_str))

        self.versioned_loaders = versioned_loaders

    def update_loaders_with_help_file_contents(self, nouns):
        loader_file_names_dict = {}
        file_name_set = set()
        for ldr_cls_name, loader in self.versioned_loaders.items():
            new_file_names = loader.get_noun_help_file_names(nouns) or []
            loader_file_names_dict[ldr_cls_name] = new_file_names
            file_name_set.update(new_file_names)

        for file_name in file_name_set:
            if file_name not in self._name_to_content:
                with open(file_name, 'r') as f:
                    self._name_to_content[file_name] = f.read()

        for ldr_cls_name, file_names in loader_file_names_dict.items():
            file_contents = {}
            for name in file_names:
                file_contents[name] = self._name_to_content[name]
            self.versioned_loaders[ldr_cls_name].update_file_contents(file_contents)

    # This method is meant to be a hook that can be overridden by an extension or module.
    @staticmethod
    def update_examples(help_file):
        pass
