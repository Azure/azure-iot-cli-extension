# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for
# full license information.
# pylint: disable=no-self-use,unused-argument

import os
import sys
import contextlib
import functools
import six

six.print_ = functools.partial(six.print_, flush=True)


# This is to prevent IoT SDK C output, but is not intrusive due to context
@contextlib.contextmanager
def block_stdout():
    devnull = open(os.devnull, 'w')
    orig_stdout_fno = os.dup(sys.stdout.fileno())
    os.dup2(devnull.fileno(), 1)
    try:
        yield
    finally:
        os.dup2(orig_stdout_fno, 1)
        devnull.close()


class Default_Msg_Callbacks(object):
    def open_complete_callback(self, context):
        return

    def send_complete_callback(self, context, messaging_result):
        return

    def feedback_received_callback(self, context, batch_user_id, batch_lock_token, feedback_records):
        six.print_('_Feedback batch received_')
        six.print_('{:<30}: {}'.format('UserId', batch_user_id))
        six.print_('{:<30}: {}'.format('LockToken', batch_lock_token))
        six.print_('{:<30}: {}'.format('Records', len(feedback_records)))
        six.print_()
        self.output_feedback_details(feedback_records)

    def output_feedback_details(self, result):
        for record in result:
            for k in sorted(record.keys()):
                six.print_('{:<30}: {}'.format(str(k), str(record[k])))
            six.print_()
