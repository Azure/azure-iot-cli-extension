# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help definitions for Product Certification Testing commands.
"""

from knack.help_files import helps


def load_help():
    # product tests
    helps[
        "iot product test"
    ] = """
        type: group
        short-summary: Manage device tests for product certification
    """
    helps[
        "iot product test create"
    ] = """
        type: command
        short-summary: Create a new product test for product certification
        examples:
        - name: Basic usage
          text: >
            az iot product test create --configuration-file {configuration_file}
        - name: Do not have service create provisioning configuration
          text: >
            az iot product test create --configuration-file {configuration_file} --skip-provisioning
        - name: Creating test with symmetric key attestation
          text: >
            az iot product test create --attestation-type SymmetricKey --device-type {device_type}
        - name: Creating test with TPM attestation
          text: >
            az iot product test create --attestation-type TPM --device-type {device_type} --endorsement-key {endorsement_key}
        - name: Creating test with x509 attestation
          text: >
            az iot product test create --attestation-type x509 --device-type {device_type} --certificate-path {certificate_path}
        - name: Creating test for Edge module
          text: >
            az iot product test create --attestation-type ConnectionString --device-type {device_type} --badge-type IotEdgeCompatible --connection-string {connection_string}
        - name: Creating test with symmetric key attestation and specified validation type
          text: >
            az iot product test create --attestation-type SymmetricKey --device-type {device_type} --validation-type Certification --product-id {product_id}
    """
    helps[
        "iot product test search"
    ] = """
        type: command
        short-summary: Search product repository for testing data
        examples:
        - name: Search by product id
          text: >
            az iot product test search --product-id {product_id}
        - name: Search by DPS registration
          text: >
            az iot product test search --registration-id {registration_id}
        - name: Search by x509 certifcate common name (CN)
          text: >
            az iot product test search --certificate-name {certificate_name}
        - name: Search by multiple values
          text: >
            az iot product test search --product-id {product_id} --certificate-name {certificate_name}
    """
    helps[
        "iot product test show"
    ] = """
        type: command
        short-summary: View product test data
        examples:
        - name: Basic usage
          text: >
            az iot product test show --test-id {test_id}
    """
    helps[
        "iot product test update"
    ] = """
        type: command
        short-summary: Update the product certification test data
        examples:
        - name: Basic usage
          text: >
            az iot product test update --test-id {test_id} --configuration-file {configuration_file}
    """
    # Product Test Tasks
    helps[
        "iot product test task"
    ] = """
        type: group
        short-summary: Manage product testing certification tasks
    """
    helps[
        "iot product test task create"
    ] = """
        type: command
        short-summary: Queue a new testing task. Only one testing task can be running at a time
        examples:
        - name: Basic usage
          text: >
            az iot product test task create --test-id {test_id}
        - name: Wait for completion and return test case
          text: >
            az iot product test task create --test-id {test_id} --wait
        - name: Wait for completion with custom polling interval to completion and return test case
          text: >
            az iot product test task create --test-id {test_id} --wait --poll-interval 5
    """
    helps[
        "iot product test task delete"
    ] = """
        type: command
        short-summary: Cancel a running task matching the specified --task-id
        examples:
        - name: Basic usage
          text: >
            az iot product test task delete --test-id {test_id} --task-id {task_id}
    """
    helps[
        "iot product test task show"
    ] = """
        type: command
        short-summary: Show the status of a testing task. Use --running for current running task or --task-id
        examples:
        - name: Task status by --task-id
          text: >
            az iot product test task show --test-id {test_id} --task-id {task_id}
        - name: Currently running task of product test
          text: >
            az iot product test task show --test-id {test_id} --running
    """
    # Test Cases
    helps[
        "iot product test case"
    ] = """
        type: group
        short-summary: Manage product testing certification test cases
    """
    helps[
        "iot product test case update"
    ] = """
        type: command
        short-summary: Update the product certification test case data
        examples:
        - name: Basic usage
          text: >
            az iot product test case update --test-id {test_id} --configuration-file {configuration_file}
    """
    helps[
        "iot product test case list"
    ] = """
        type: command
        short-summary: List the test cases of a product certification test
        examples:
        - name: Basic usage
          text: >
            az iot product test case list --test-id {test_id}
    """
    # Test Runs
    helps[
        "iot product test run"
    ] = """
        type: group
        short-summary: Manage product testing certification test runs
    """
    helps[
        "iot product test run submit"
    ] = """
        type: command
        short-summary: Submit a completed test run to the partner/product service
        examples:
        - name: Basic usage
          text: >
            az iot product test run submit --test-id {test_id} --run-id {run_id}
    """
    helps[
        "iot product test run show"
    ] = """
        type: command
        short-summary: Show the status of a testing run.
        examples:
        - name: Latest product test run
          text: >
            az iot product test run show --test-id {test_id}
        - name: Testing status by --run-id
          text: >
            az iot product test run show --test-id {test_id} --run-id {run_id}
    """
