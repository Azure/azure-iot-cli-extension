# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.testsdk import LiveScenarioTest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.settings import UserTypes
from azext_iot.common.utility import get_current_user

terms_offerId = "jlian-test-offer-paid"
terms_planId = "premium"
terms_publisherId = "azure-iot"
terms_urn = "azure-iot:jlian-test-offer-paid:premium"


@pytest.mark.usefixtures("setup_edge_image_terms_tests")
class TestIoTEdgeImageTerms(LiveScenarioTest):
    def __init__(self, test_scenario):
        assert test_scenario

        super(TestIoTEdgeImageTerms, self).__init__(test_scenario)
        self.embedded_cli = EmbeddedCLI()
        self.current_user = get_current_user()

    @pytest.fixture(scope="class")
    def setup_edge_image_terms_tests(self):
        if self.current_user["type"] == UserTypes.user.value:
            # Ensure Edge image offer terms are not accepted before the test starts
            self.cmd(
                "iot edge image terms cancel --offer {} --plan {} --publisher {}".format(
                    terms_offerId, terms_planId, terms_publisherId
                )
            )

    def test_edge_image_terms_commands(self):
        if self.current_user["type"] == UserTypes.user.value:
            offer_checks = [
                self.check("product", terms_offerId),
                self.check("plan", terms_planId),
                self.check("publisher", terms_publisherId),
            ]

            # Show IoT Edge module terms offer
            self.cmd(
                "iot edge image terms show --offer {} --plan {} --publisher {}".format(
                    terms_offerId, terms_planId, terms_publisherId
                ),
                checks=offer_checks.append(self.check("accepted", "false"))
            )

            # Accept IoT Edge module terms offer
            self.cmd(
                "iot edge image terms accept --offer {} --plan {} --publisher {}".format(
                    terms_offerId, terms_planId, terms_publisherId
                ),
                checks=offer_checks.append(self.check("accepted", "true"))
            )

            # Show the accepted IoT Edge module terms offer using URN
            self.cmd(
                "iot edge image terms show --urn {}".format(
                    terms_urn
                ),
                checks=offer_checks.append(self.check("accepted", "true"))
            )

            # Cancel IoT Edge module terms offer
            self.cmd(
                "iot edge image terms cancel --offer {} --plan {} --publisher {}".format(
                    terms_offerId, terms_planId, terms_publisherId
                ),
                checks=offer_checks.append(self.check("accepted", "false"))
            )

            # Error - providing offer, plan and publisher when URN is already provided
            self.cmd(
                "iot edge image terms show --urn {} --offer {} --plan {} --publisher {}".format(
                    terms_urn, terms_offerId, terms_planId, terms_publisherId
                ),
                expect_failure=True,
            )

            # Error - invalid URN format
            self.cmd(
                "iot edge image terms show --urn {}".format(
                    "bad_URN"
                ),
                expect_failure=True,
            )

            # Error - invalid offer
            self.cmd(
                "iot edge image terms show --offer {} --plan {} --publisher {}".format(
                    "invalid_offer", terms_planId, terms_publisherId
                ),
                expect_failure=True,
            )

            # Error - invalid publisher
            self.cmd(
                "iot edge image terms show --offer {} --plan {} --publisher {}".format(
                    terms_offerId, terms_planId, "invalid_publisher"
                ),
                expect_failure=True,
            )
        else:
            # Error - Command run by a service principal user
            self.cmd(
                "iot edge image terms show --offer {} --plan {} --publisher {}".format(
                    terms_offerId, terms_planId, terms_publisherId
                ),
                expect_failure=True,
            )
