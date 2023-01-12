# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.fileops import tar_directory, write_content_to_file
import pytest
import os
from os.path import join, exists
from azure.cli.core.azclierror import FileOperationError

current_or_empty_dirs = ['./', '.', '', None]


class TestFileOperations(object):

    @pytest.mark.parametrize(
        "content, destination, file_name, overwrite, error, remove_after_test",
        [
            # initial create
            ("test_file_contents", "./", "new_file.txt", False, None, False),
            # fileoperationerror trying to overwrite existing file with overwrite: false
            ("new_test_file_contents", "./", "new_file.txt", False, FileOperationError, False),
            # force overwrite new file
            ("overwrite_file_contents", "./", "new_file.txt", True, None, True),
            ("second_test_file_contents", "test_dir", "new_file.txt", True, None, True),
        ]
    )
    def test_write_content_to_file(self, set_cwd, content, destination, file_name, overwrite, error, remove_after_test):
        try:
            write_content_to_file(content=content, destination=destination, file_name=file_name, overwrite=overwrite)
            with open(join(destination, file_name), "rt", encoding="utf-8") as f:
                assert f.read() == content
            if remove_after_test:
                os.remove(join(destination, file_name))
                if destination not in current_or_empty_dirs:
                    os.rmdir(destination)
        except Exception as ex:
            assert (error and isinstance(ex, error))

    @pytest.mark.parametrize(
        "target_directory, tarfile_path, tarfile_name, overwrite, error, delete_after_test",
        [
            ("./", "./", "test_tar", False, None, False),
            ("./", "./", "test_tar", False, FileOperationError, False),
            ("./", "./", "test_tar", True, None, True),
            ("./", "new_dir", "test_tar", True, None, True),
        ]
    )
    def test_tar_directory(self, set_cwd, target_directory, tarfile_path, tarfile_name, overwrite, error, delete_after_test):
        try:
            tar_directory(
                target_directory=target_directory,
                tarfile_path=tarfile_path,
                tarfile_name=tarfile_name,
                overwrite=overwrite
            )
            assert exists(join(tarfile_path, f"{tarfile_name}.tgz"))
            if delete_after_test:
                os.remove(join(tarfile_path, f"{tarfile_name}.tgz"))
                if tarfile_path not in current_or_empty_dirs:
                    os.rmdir(tarfile_path)
        except Exception as ex:
            assert (error and isinstance(ex, error))
