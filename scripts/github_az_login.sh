#!/bin/bash
set -e

# get JWT from GitHub's OIDC provider
# see https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect#updating-your-actions-for-oidc
jwt_token=$(
    curl \
        -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
        "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=api://AzureADTokenExchange" \
        --silent \
    | jq -r ".value"
)

# perform OIDC token exchange
az login \
    --service-principal -u $AZURE_CLIENT_ID \
    --tenant $AZURE_TENANT_ID \
    --federated-token $jwt_token \
    -o none

az account set \
    --subscription $AZURE_SUBSCRIPTION_ID \
    -o none