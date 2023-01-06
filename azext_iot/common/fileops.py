# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from os import makedirs, remove, listdir
from os.path import exists, join
from pathlib import PurePath
from typing import Union
from azure.cli.core.azclierror import FileOperationError


"""
fileops: Functions for working with files.
"""


def write_content_to_file(
    content: Union[str, bytes],
    destination: str,
    file_name: str,
    overwrite: bool = False,
):
    dest_path = PurePath(destination)
    file_path = dest_path.joinpath(file_name)

    if exists(file_path) and not overwrite:
        raise FileOperationError(f"File already exists at path: {file_path}")
    if overwrite and destination:
        makedirs(destination, exist_ok=True)
    write_content = bytes(content, "utf-8") if isinstance(content, str) else content
    with open(file_path, "wb") as f:
        f.write(write_content)


def tar_directory(
    target_directory: str,
    tarfile_path: str,
    tarfile_name: str,
    overwrite: bool = False,
):
    full_path = join(tarfile_path, f"{tarfile_name}.tgz")
    if exists(full_path):
        if not overwrite:
            raise FileOperationError(f"File {full_path} already exists")
        remove(full_path)
    if not exists(tarfile_path):
        makedirs(tarfile_path, exist_ok=overwrite)
    import tarfile
    with tarfile.open(full_path, "w:gz") as tar:
        for file_name in listdir(target_directory):
            tar.add(join(target_directory, file_name), file_name)
