#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.

set -euo pipefail
openssl_bin="$(brew --prefix openssl@3)/bin"
"$openssl_bin/openssl" version
"$openssl_bin/openssl" x509 -help 2>&1 | grep -- '-copy_extensions'
"$openssl_bin/openssl" req -help 2>&1 | grep -- '-addext'
