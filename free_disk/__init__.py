"""
Delete file with the oldest modification date
until a minimum of --free-bytes are available on the respective disk.
"""

import argparse
import datetime
import logging
import os
import re
import shutil
import sys

# https://en.wikipedia.org/wiki/Template:Quantities_of_bytes
_DATA_SIZE_UNIT_BYTE_CONVERSION_FACTOR = {
    "B": 1,
    "kB": 10**3,
    "KB": 10**3,
    "MB": 10**6,
    "GB": 10**9,
    "TB": 10**12,
    "KiB": 2**10,
    "MiB": 2**20,
    "GiB": 2**30,
    "TiB": 2**40,
}


def _data_size_to_bytes(size_with_unit: str) -> int:
    match = re.match(r"^([\d\.]+)\s*([A-Za-z]+)?$", size_with_unit)
    if not match:
        raise ValueError(f"Unable to parse data size {size_with_unit!r}")
    unit_symbol = match.group(2)
    if unit_symbol:
        try:
            byte_conversion_factor = _DATA_SIZE_UNIT_BYTE_CONVERSION_FACTOR[unit_symbol]
        except KeyError as exc:
            raise ValueError(f"Unknown data size unit symbol {unit_symbol!r}") from exc
    else:
        byte_conversion_factor = 1
    byte_size = float(match.group(1)) * byte_conversion_factor
    return int(round(byte_size, 0))


def _main() -> None:
    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument("-d", "--debug", action="store_true")
    argparser.add_argument(
        "--track-bytes-deleted",
        action="store_true",
        help="Use total size of deleted files instead of filesystem free space for completion. This is useful on filesystems like ZFS with laggy free-disk indicators",
    )
    argparser.add_argument(
        "--delete-re",
        action="store",
        help="Only delete files matching regexp. examples: .*mp4$",
        default=".*",
    )
    argparser.add_argument(
        "--free-bytes",
        type=_data_size_to_bytes,
        required=True,
        help="examples: 1024, 1024B, 4KiB, 4KB, 2TB",
    )
    argparser.add_argument("root_dir_path", metavar="ROOT_DIR")
    args = argparser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s:%(levelname)s:%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    disk_usage = shutil.disk_usage(args.root_dir_path)
    logging.debug(disk_usage)
    space_to_free = args.free_bytes - disk_usage.free
    space_freed = 0

    def sufficient_free_space(track_bytes_deleted=False):
        if track_bytes_deleted:
            return space_to_free - space_freed <= 0
        else:
            return shutil.disk_usage(args.root_dir_path).free >= args.free_bytes

    logging.debug(f'Required free bytes: {args.free_bytes}. {space_to_free} bytes to free')
    if sufficient_free_space():
        logging.debug("Requirement already fulfilled")
        return
    file_paths = [
        os.path.join(dirpath, filename)
        for dirpath, _, filenames in os.walk(args.root_dir_path)
        for filename in filenames
    ]
    delete_re = re.compile(args.delete_re)
    stat_paths = [(os.stat(p), p) for p in file_paths if delete_re.match(p)]
    stat_paths.sort(key=lambda x: x[0].st_mtime)
    removed_files_counter = 0
    last_mtime = None

    for file_stat, file_path in stat_paths:
        if sufficient_free_space(args.track_bytes_deleted):
            break
        os.remove(file_path)
        logging.debug(
            f"Freed {file_stat.st_size}/{space_freed} bytes by removing file {file_path}"
        )
        space_freed += file_stat.st_size
        removed_files_counter += 1
        last_mtime = file_stat.st_mtime
    if removed_files_counter == 0:
        logging.warning("No files to remove")
    else:
        assert last_mtime is not None  # for mypy
        logging.info(
            "Removed %d file(s) with modification date <= %sZ. Deleted %d bytes. Filesystem freed %d bytes.",
            removed_files_counter,
            datetime.datetime.utcfromtimestamp(last_mtime).isoformat("T"),
            space_freed,
            shutil.disk_usage(args.root_dir_path).free - disk_usage.free,
        )

    # exit with 0 if sufficient_free_space returns True
    sys.exit(not sufficient_free_space(args.track_bytes_deleted))
