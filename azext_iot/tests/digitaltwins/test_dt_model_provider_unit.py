# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.digitaltwins.providers import model as subject
from azext_iot.tests.digitaltwins.dt_helpers import generate_generic_id


# Rules:
# Contents needs to be a list + can have fakes
# if string - add string (dtmi)
# if dict - need to recurse (object)
# if list - need to iterate - will have strings or dicts


def parse_model(json_input):
    # Note that models will not count for their own dtmi id's
    model = {
        "@id": json_input['id'],
        "@type": "Interface"
    }
    dependencies = set()
    if 'contents' in json_input:
        parsed = []
        for content in json_input['contents']:
            name = generate_generic_id()
            if content == 'f1':
                parsed.append({
                    '@type': "Fake",
                    'name': name,
                    'schema': "notadtmi"
                })
            else:
                component_schema, component_dependencies = parse_extends(content)
                parsed.append({
                    '@type': "Component",
                    'name': name,
                    'schema': component_schema
                })
                dependencies.update(component_dependencies)
        model['contents'] = parsed

    if 'extends' in json_input:
        extends_schema, extends_dependencies = parse_extends(json_input['extends'])
        model['extends'] = extends_schema
        dependencies.update(extends_dependencies)

    return model, dependencies


def parse_extends(schema_input):
    dependencies = set()

    if isinstance(schema_input, str):
        dependencies.add(schema_input)
        return schema_input, dependencies

    if isinstance(schema_input, dict):
        model, dependencies = parse_model(schema_input)
        dependencies.add(schema_input['id'])
        return model, dependencies

    schema = []
    for schema_item in schema_input:
        if isinstance(schema_item, str):
            schema.append(schema_item)
            dependencies.add(schema_item)
        if isinstance(schema_item, dict):
            schema_model, schema_dependencies = parse_model(schema_item)
            schema.append(schema_model)
            dependencies.add(schema_item['id'])
            dependencies.update(schema_dependencies)
    return schema, dependencies


class TestGetModelDependencies(object):
    @pytest.mark.parametrize(
        "test_input", [
            {'id': 'm0'},
            {'id': 'm0', 'contents': []},
            {'id': 'm0', 'contents': ['f1']},
            {'id': 'm0', 'contents': ['f1', 'f1']},

            {'id': 'm0', 'contents': ['m1']},
            {'id': 'm0', 'contents': ['f1', 'm1']},
            {'id': 'm0', 'contents': ['m1', 'm2']},
            {'id': 'm0', 'contents': ['m1', 'm1']},
            {'id': 'm0', 'contents': ['m1', 'm2']},
            {'id': 'm0', 'contents': ['m1', 'f1', 'm2']},
            {'id': 'm0', 'contents': [{'id': 'm1'}]},
            {'id': 'm0', 'contents': ['f1', {'id': 'm1'}]},
            {'id': 'm0', 'contents': ['m1', {'id': 'm2'}]},
            {'id': 'm0', 'contents': [{'id': 'm1'}, 'm1']},
            {'id': 'm0', 'contents': [{'id': 'm1'}, {'id': 'm2'}]},
            {'id': 'm0', 'contents': [{'id': 'm1'}, 'f1', {'id': 'm2'}]},

            {'id': 'm0', 'contents': [['m1']]},
            {'id': 'm0', 'contents': ['f1', ['m1']]},
            {'id': 'm0', 'contents': [['m1'], 'm2']},
            {'id': 'm0', 'contents': [['m1'], ['m1']]},
            {'id': 'm0', 'contents': [['m1'], 'm2']},
            {'id': 'm0', 'contents': [['m1'], 'f1', 'm2']},
            {'id': 'm0', 'contents': [[{'id': 'm1'}]]},
            {'id': 'm0', 'contents': ['f1', [{'id': 'm1'}]]},
            {'id': 'm0', 'contents': [['m1', {'id': 'm2'}]]},
            {'id': 'm0', 'contents': [[{'id': 'm1'}], 'm1']},
            {'id': 'm0', 'contents': [[{'id': 'm1'}, 'm2'], {'id': 'm3'}, 'm4']},
            {'id': 'm0', 'contents': [[{'id': 'm1'}], 'f1', [{'id': 'm1'}]]},
            {'id': 'm0', 'contents': [{'id': 'm1', 'contents': ['f1']}]},
            {'id': 'm0', 'contents': [{'id': 'm1', 'contents': ['m2']}]},
            {'id': 'm0', 'contents': [{'id': 'm1', 'contents': ['m2', 'm3']}]},
            {'id': 'm0', 'contents': [
                'f1',
                'm1',
                {'id': 'm2', 'contents': ['f1', 'm3', {'id': 'm4'}]}
            ]},
            {'id': 'm0', 'contents': [
                {'id': 'm1', 'contents': ['m2', 'm3']},
                'f1',
                {'id': 'm4', 'contents': ['m3', 'm5']}
            ]},
            {'id': 'm0', 'contents': [
                {'id': 'm1', 'contents': ['m2', {'id': 'm3'}]},
                {'id': 'm4', 'contents': ['m5', {'id': 'm6'}]}
            ]},
            {'id': 'm0', 'contents': [
                {'id': 'm1', 'contents': ['m2', {'id': 'm3'}]},
                {'id': 'm3', 'contents': ['m4', {'id': 'm5'}]}
            ]},

            {'id': 'm0', 'extends': 'm1'},
            {'id': 'm0', 'extends': ['m1']},
            {'id': 'm0', 'extends': ['m1', 'm1']},
            {'id': 'm0', 'extends': ['m1', 'm2']},
            {'id': 'm0', 'extends': {'id': 'm1'}},
            {'id': 'm0', 'extends': [{'id': 'm1'}]},
            {'id': 'm0', 'extends': ['m1', {'id': 'm1'}]},
            {'id': 'm0', 'extends': ['m1', {'id': 'm2'}]},
            {'id': 'm0', 'extends': ['m1', 'm2', {'id': 'm2'}]},
            {'id': 'm0', 'extends': {'id': 'm1', 'extends': 'm2'}},
            {'id': 'm0', 'extends': {'id': 'm1', 'extends': ['m2']}},
            {'id': 'm0', 'extends': {'id': 'm1', 'extends': 'm1'}},
            {'id': 'm0', 'extends': {'id': 'm1', 'extends': ['m2', 'm3']}},
            {'id': 'm0', 'extends': {'id': 'm1', 'extends': ['m1', 'm2', 'm2']}},
            {'id': 'm0', 'extends': {'id': 'm1', 'extends': {'id': 'm2'}}},
            {'id': 'm0', 'extends': {'id': 'm1', 'extends': {'id': 'm1'}}},
            {'id': 'm0', 'extends': {'id': 'm1', 'extends': [{'id': 'm2'}]}},
            {'id': 'm0', 'extends': {'id': 'm1', 'extends': ['m1', 'm2', {'id': 'm2'}]}},

            {'id': 'm0', 'contents': ['f1'], 'extends': 'm1'},
            {'id': 'm0', 'contents': ['f1'], 'extends': ['m1']},
            {'id': 'm0', 'contents': ['f1'], 'extends': [{'id': 'm1'}]},
            {'id': 'm0', 'contents': ['f1'], 'extends': {'id': 'm1'}},
            {'id': 'm0', 'contents': ['m1'], 'extends': 'm1'},
            {'id': 'm0', 'contents': ['m1'], 'extends': ['m1']},
            {'id': 'm0', 'contents': ['m1'], 'extends': [{'id': 'm1'}]},
            {'id': 'm0', 'contents': ['m1'], 'extends': {'id': 'm1'}},
            {'id': 'm0', 'contents': [{'id': 'm1'}], 'extends': 'm1'},
            {'id': 'm0', 'contents': [{'id': 'm1'}], 'extends': ['m1']},
            {'id': 'm0', 'contents': [{'id': 'm1'}], 'extends': [{'id': 'm1'}]},
            {'id': 'm0', 'contents': [{'id': 'm1'}], 'extends': {'id': 'm1'}},
            {'id': 'm0', 'contents': [['m1']], 'extends': 'm1'},
            {'id': 'm0', 'contents': [['m1']], 'extends': ['m1']},
            {'id': 'm0', 'contents': [['m1']], 'extends': [{'id': 'm1'}]},
            {'id': 'm0', 'contents': [['m1']], 'extends': {'id': 'm1'}},
            {'id': 'm0', 'contents': [[{'id': 'm1'}]], 'extends': 'm1'},
            {'id': 'm0', 'contents': [[{'id': 'm1'}]], 'extends': ['m1']},
            {'id': 'm0', 'contents': [[{'id': 'm1'}]], 'extends': [{'id': 'm1'}]},
            {'id': 'm0', 'contents': [[{'id': 'm1'}]], 'extends': {'id': 'm1'}},
            {'id': 'm0', 'contents': ['m1'], 'extends': 'm2'},
            {'id': 'm0', 'contents': ['m1'], 'extends': ['m2']},
            {'id': 'm0', 'contents': ['m1'], 'extends': [{'id': 'm2'}]},
            {'id': 'm0', 'contents': ['m1'], 'extends': {'id': 'm2'}},
            {'id': 'm0', 'contents': [{'id': 'm1'}], 'extends': 'm2'},
            {'id': 'm0', 'contents': [{'id': 'm1'}], 'extends': ['m2']},
            {'id': 'm0', 'contents': [{'id': 'm1'}], 'extends': [{'id': 'm2'}]},
            {'id': 'm0', 'contents': [{'id': 'm1'}], 'extends': {'id': 'm2'}},
            {'id': 'm0', 'contents': [['m1']], 'extends': 'm2'},
            {'id': 'm0', 'contents': [['m1']], 'extends': ['m2']},
            {'id': 'm0', 'contents': [['m1']], 'extends': [{'id': 'm2'}]},
            {'id': 'm0', 'contents': [['m1']], 'extends': {'id': 'm2'}},
            {'id': 'm0', 'contents': [[{'id': 'm1'}]], 'extends': 'm2'},
            {'id': 'm0', 'contents': [[{'id': 'm1'}]], 'extends': ['m2']},
            {'id': 'm0', 'contents': [[{'id': 'm1'}]], 'extends': [{'id': 'm2'}]},
            {'id': 'm0', 'contents': [[{'id': 'm1'}]], 'extends': {'id': 'm2'}},
            {'id': 'm0', 'contents': [{'id': 'm1', 'extends': 'm2'}], 'extends': [{'id': 'm3', 'contents': ['m4']}]},
            {
                'id': 'm0',
                'contents': [{'id': 'm1', 'extends': ['m2', {'id': 'm3'}]}],
                'extends': [{'id': 'm3', 'contents': ['m2', ['m3', {'id': 'm4'}], {'id': 'm5'}]}]
            },
            {
                'id': 'm0',
                'extends': ['m2', {'id': 'm3', 'contents': [['m4'], {'id': 'm5', 'extends': 'm6'}]}]
            }
        ]
    )
    def test_get_model_dependencies(self, test_input):
        input_model, expected = parse_model(test_input)
        result = subject.get_model_dependencies(input_model)
        assert len(result) == len(set(result))
        assert set(result) == expected
