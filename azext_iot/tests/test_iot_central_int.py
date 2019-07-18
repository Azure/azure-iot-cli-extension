# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=too-many-statements,wrong-import-position,too-many-lines,import-error
from azure.cli.testsdk import LiveScenarioTest

AAD_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6InU0T2ZORlBId0VCb3NIanRyYXVPYlY4NExuWSIsImtpZCI6InU0T2ZORlBId0VCb3NIanRyYXVPYlY4NExuWSJ9.eyJhdWQiOiJodHRwczovL2FwcHMuYXp1cmVpb3RjZW50cmFsLmNvbSIsImlzcyI6Imh0dHBzOi8vc3RzLndpbmRvd3MubmV0LzcyZjk4OGJmLTg2ZjEtNDFhZi05MWFiLTJkN2NkMDExZGI0Ny8iLCJpYXQiOjE1NjM0ODk3NjksIm5iZiI6MTU2MzQ4OTc2OSwiZXhwIjoxNTYzNDkzNjY5LCJhY3IiOiIxIiwiYWlvIjoiQVZRQXEvOE1BQUFBZld3SjNhTUtrRFltVjJ3SEVqNjErNmdQNXlWbjFxLzRkVXRhZk9IUnlpVzhZeFFUbzVwSGdJenFFcE90blA4SDdFWWNEMTVZME4xRi9rS0c2UkNnNVV5eDVoNUZnYStIY3lUUWRydFpybk09IiwiYW1yIjpbIndpYSIsIm1mYSJdLCJhcHBpZCI6IjA0YjA3Nzk1LThkZGItNDYxYS1iYmVlLTAyZjllMWJmN2I0NiIsImFwcGlkYWNyIjoiMCIsImZhbWlseV9uYW1lIjoiQmFya2VyIiwiZ2l2ZW5fbmFtZSI6IkphY2siLCJpbl9jb3JwIjoidHJ1ZSIsImlwYWRkciI6IjE2Ny4yMjAuMjQuNTIiLCJuYW1lIjoiSmFjayBCYXJrZXIiLCJvaWQiOiI1MjMzYzczZS0yZjc5LTRjYWMtYjk1NS02NmQxNjk0ODA5OTQiLCJvbnByZW1fc2lkIjoiUy0xLTUtMjEtMTI0NTI1MDk1LTcwODI1OTYzNy0xNTQzMTE5MDIxLTE4Nzg5MTkiLCJwdWlkIjoiMTAwMzIwMDAzNDEyQkEwMCIsInNjcCI6InVzZXJfaW1wZXJzb25hdGlvbiIsInN1YiI6ImF3dUxYa2stN2RsNEVNX3BrRXNtbGVHOEZ0dmN3bURjdVlFaW00TENtZGMiLCJ0aWQiOiI3MmY5ODhiZi04NmYxLTQxYWYtOTFhYi0yZDdjZDAxMWRiNDciLCJ1bmlxdWVfbmFtZSI6ImphYmFya0BtaWNyb3NvZnQuY29tIiwidXBuIjoiamFiYXJrQG1pY3Jvc29mdC5jb20iLCJ1dGkiOiJ0bTZOWk16OG1rSzVneDQ4TGFNSEFBIiwidmVyIjoiMS4wIn0.CHJ2gdGg3CS_SiHFq0KpksIYbzZbM9usmbcRIRA7ftzYLa5ezFW0cNxkhUW3hXYbAOUj1W0WKE6wtaS3BFjqVHaY-wb6CziCJ1dFouBi7qVFDsE53tfdIohzTXBHnf40cW51dYRmvw2pNE4cexWRHtnIOowCt3C5jCPJlh97pviUSDL6dD67kchPOuR7m9bnq6sZpb-dk43sCgA_nns7F5TIqRqW6HhHflvY_p3pOdH6-CU7wztk8e-wfyrQdS7ze1cZQ38FPH0MwURmtHHnBXT--OK_HptehgjGkdQa8yJ5r4RtZBs07xa74vZTcZTm08ljVpi9IsrUIzoMeJirTw"
APP_ID = ""
DEVICE_ID = ""


class TestIotCentral(LiveScenarioTest):
    def __init__(self, _):
        super(TestIotCentral, self).__init__(_)
        return

    def setUp(self):
        return

    def tearDown(self):
        return

    def test_hub(self):

        self.cmd('az iotcentral device show --app-id "{}"  --device-id "{}"  --aad-token {}'.format(APP_ID, DEVICE_ID, AAD_TOKEN),
                 checks=[self.exists('sas')])
