# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.core.azclierror import ArgumentUsageError


_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def _patch_subscription_id(monkeypatch):
    monkeypatch.setattr(
        "azext_iot.adr.providers.job.get_subscription_id",
        lambda _ctx: _SUBSCRIPTION_ID,
    )


def _create_job(provider, **overrides):
    kwargs = {
        "job_name": "job",
        "namespace_name": "namespace",
        "resource_group_name": "rg",
        "update_provider": "Contoso",
        "update_name": "firmware",
        "update_version": "1.2.3",
        "target_group_name": "group",
        "location": "eastus",
    }
    kwargs.update(overrides)
    return provider.create(**kwargs)


def test_software_update_job_payload(fixture_job_provider, mock_poller):
    fixture_job_provider.client.jobs.begin_create_or_replace.return_value = (
        mock_poller({"name": "job"})
    )

    result = _create_job(
        fixture_job_provider,
        job_type="SoftwareUpdate",
        description="Production rollout",
        tags={"env": "prod"},
    )

    assert result == {"name": "job"}
    target_id = (
        f"/subscriptions/{_SUBSCRIPTION_ID}/resourceGroups/rg/providers/"
        "Microsoft.DeviceRegistry/namespaces/namespace/groups/group"
    )
    fixture_job_provider.client.jobs.begin_create_or_replace.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
        resource={
            "location": "eastus",
            "properties": {
                "jobType": "SoftwareUpdate",
                "description": "Production rollout",
                "target": {"resourceId": target_id},
                "definition": {
                    "schedulingType": "Continuous",
                    "updateResourceId": (
                        "updates/providers/Contoso/names/firmware/versions/1.2.3"
                    ),
                },
            },
            "tags": {"env": "prod"},
        },
    )


def test_onboarding_update_job_has_no_target(fixture_job_provider, mock_poller):
    fixture_job_provider.client.jobs.begin_create_or_replace.return_value = (
        mock_poller({"name": "onboarding"})
    )

    _create_job(
        fixture_job_provider,
        job_name="onboarding",
        job_type="OnboardingUpdate",
        target_group_name=None,
    )

    properties = fixture_job_provider.client.jobs.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]["properties"]
    assert properties["jobType"] == "OnboardingUpdate"
    assert properties["definition"]["schedulingType"] == "Continuous"
    assert "target" not in properties


def test_job_create_inherits_parent_namespace_location(
    fixture_job_provider, mock_poller
):
    fixture_job_provider.client.namespaces.get.return_value = {"location": "westus2"}
    fixture_job_provider.client.jobs.begin_create_or_replace.return_value = (
        mock_poller({})
    )

    _create_job(fixture_job_provider, location=None)

    fixture_job_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name="rg", namespace_name="namespace"
    )
    resource = fixture_job_provider.client.jobs.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert resource["location"] == "westus2"


@pytest.mark.parametrize("job_type", ["Update", "Action", "State", "unknown"])
def test_job_create_rejects_unsupported_type(fixture_job_provider, job_type):
    with pytest.raises(
        ArgumentUsageError, match="SoftwareUpdate or OnboardingUpdate"
    ):
        _create_job(fixture_job_provider, job_type=job_type)
    fixture_job_provider.client.jobs.begin_create_or_replace.assert_not_called()


def test_software_update_requires_target_group(fixture_job_provider):
    with pytest.raises(ArgumentUsageError, match="--target-group-name is required"):
        _create_job(
            fixture_job_provider,
            job_type="SoftwareUpdate",
            target_group_name=None,
        )


def test_onboarding_update_rejects_target_group(fixture_job_provider):
    with pytest.raises(ArgumentUsageError, match="cannot be used"):
        _create_job(fixture_job_provider, job_type="OnboardingUpdate")


@pytest.mark.parametrize(
    "updates",
    [
        {"update_provider": None},
        {"update_name": None},
        {"update_version": None},
        {
            "update_provider": None,
            "update_name": None,
            "update_version": None,
        },
    ],
)
def test_job_create_requires_complete_update_id(fixture_job_provider, updates):
    with pytest.raises(ArgumentUsageError, match="are required"):
        _create_job(fixture_job_provider, **updates)


def test_job_create_no_wait(fixture_job_provider, mock_poller):
    poller = mock_poller({"name": "job"})
    fixture_job_provider.client.jobs.begin_create_or_replace.return_value = poller

    result = _create_job(fixture_job_provider, no_wait=True)

    assert result is poller
    poller.result.assert_not_called()


@pytest.mark.parametrize(
    "tags,expected", [({"env": "staging"}, {"env": "staging"}), ({}, {})]
)
def test_job_update_is_synchronous_tags_only(
    fixture_job_provider, tags, expected
):
    fixture_job_provider.client.jobs.update.return_value = {"name": "job"}

    result = fixture_job_provider.update(
        "job", "namespace", "rg", tags=tags
    )

    assert result == {"name": "job"}
    fixture_job_provider.client.jobs.update.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
        properties={"tags": expected},
    )


def test_job_update_rejects_empty_update(fixture_job_provider):
    with pytest.raises(ArgumentUsageError, match="Nothing to update"):
        fixture_job_provider.update("job", "namespace", "rg")
    fixture_job_provider.client.jobs.update.assert_not_called()


def test_job_update_rejects_immutable_fields(fixture_job_provider):
    with pytest.raises(ArgumentUsageError, match="Only --tags"):
        fixture_job_provider.update(
            "job",
            "namespace",
            "rg",
            tags={"a": "b"},
            description="immutable",
        )


def test_job_show_and_list(fixture_job_provider):
    fixture_job_provider.client.jobs.get.return_value = {"name": "job"}
    fixture_job_provider.client.jobs.list_by_namespace.return_value = iter(
        [{"name": "one"}, {"name": "two"}]
    )

    assert fixture_job_provider.show("job", "namespace", "rg") == {"name": "job"}
    assert fixture_job_provider.list("namespace", "rg") == [
        {"name": "one"},
        {"name": "two"},
    ]
    fixture_job_provider.client.jobs.get.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
    )
    fixture_job_provider.client.jobs.list_by_namespace.assert_called_once_with(
        resource_group_name="rg", namespace_name="namespace"
    )


def test_job_delete_calls_jobs_delete_directly(fixture_job_provider, mock_poller):
    fixture_job_provider.client.jobs.begin_delete.return_value = mock_poller(None)

    fixture_job_provider.delete("job", "namespace", "rg")

    fixture_job_provider.client.jobs.begin_delete.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
    )
    fixture_job_provider.client.job_runs.list_by_job.assert_not_called()


def test_job_delete_no_wait(fixture_job_provider, mock_poller):
    poller = mock_poller(None)
    fixture_job_provider.client.jobs.begin_delete.return_value = poller

    result = fixture_job_provider.delete(
        "job", "namespace", "rg", no_wait=True
    )

    assert result is poller
    poller.result.assert_not_called()


def test_job_create_forwards_display_name(fixture_job_provider, mock_poller):
    """JobProperties.displayName is writable at create in 2026-11-02-preview."""
    fixture_job_provider.client.jobs.begin_create_or_replace.return_value = mock_poller({})

    _create_job(fixture_job_provider, display_name="Production rollout")

    body = fixture_job_provider.client.jobs.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert body["properties"]["displayName"] == "Production rollout"


def test_job_provider_has_no_schedule_operation(fixture_job_provider):
    """Jobs_Schedule was removed in 2026-11-02-preview.

    Scheduling now happens through ``JobRuns_CreateOrReplace``
    (``az iot adr ns job run create --scheduled-time``).
    """
    assert not hasattr(fixture_job_provider, "schedule")
    assert not hasattr(fixture_job_provider.client.jobs, "begin_schedule")
