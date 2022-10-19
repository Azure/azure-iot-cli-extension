import tarfile
from os import makedirs, remove, listdir
from os.path import exists, join
from pathlib import PurePath
from typing import Optional, Union
from azure.cli.core.azclierror import FileOperationError


# TODO - Unit test
def write_content_to_file(
    content: Union[str, bytes],
    destination: str,
    file_name: str,
    overwrite: Optional[bool] = False,
):
    dest_path = PurePath(destination)
    file_path = dest_path.joinpath(file_name)

    if exists(file_path) and not overwrite:
        raise FileOperationError(f"File already exists at path: {file_path}")
    if overwrite:
        makedirs(destination, exist_ok=True)
    write_content = bytes(content, "utf-8") if isinstance(content, str) else content
    with open(file_path, "wb") as f:
        f.write(write_content)


# TODO - Unit test
def create_directory_tar_archive(
    target_directory: str,
    tarfile_path: str,
    tarfile_name: str,
    overwrite: Optional[bool] = False,
):
    tar_path = join(tarfile_path, f"{tarfile_name}.tgz")
    if exists(tar_path):
        if not overwrite:
            raise FileOperationError(f"File {tar_path} already exists")
        remove(tar_path)

    with tarfile.open(
        tar_path,
        "w:gz",
    ) as tar:
        for file_name in listdir(target_directory):
            tar.add(join(target_directory, file_name), file_name)
