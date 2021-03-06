import os
import logging
import random
import string
import configparser
from typing import Dict, List, Optional
from tempfile import TemporaryDirectory
import pysam
from functools import wraps

from .sglib import (
    read_gene_table,
    read_snp_table,
    build_snpdb,
    read_star_table,
    build_stardb,
    StarAllele,
)

LINE_BREAK1 = "-" * 70
LINE_BREAK2 = "*" * 70

def sm_tag(bam: str) -> str:
    """
    Extract SM tag from BAM file.

    Returns:
        str: SM tag.

    Args:
        bam (str): BAM file.
    """

    header = pysam.view("-H", bam).strip().split("\n")

    l = []

    for line in header:
        fields = line.split("\t")
        if "@RG" == fields[0]:
            for field in fields:
                if "SM:" in field:
                    l.append(field.replace("SM:", ""))

    l = list(set(l))

    if not l:
        raise ValueError(f"SM tag not found: {bam}")

    if len(l) > 1:
        logger.warning(
            f"Multiple SM tags found (will return the first one): {bam}")
        result = l[0]
    else:
        result = l[0]

    return result

def is_chr(bam: str) -> bool:
    """
    Check whether SN tags in BAM file contain "chr" string.

    Returns:
        bool: True if found.

    Args:
        bam (str): BAM file.
    """

    header = pysam.view("-H", bam).strip().split("\n")

    l = []

    for line in header:
        fields = line.split("\t")
        if "@SQ" == fields[0]:
            for field in fields:
                if "SN:" in field:
                    l.append(field.replace("SN:", ""))

    return any(["chr" in x for x in l])

def get_stardb(tg: str, gb: str) -> Dict[str, StarAllele]:
    """
    Get StarAllele database.

    Returns:
        dict[str, StarAllele]: StarAllele objects.

    Args:
        tg (str): Target gene.
        gb (str): Genome build.

    Examples:

        >>> stardb = get_stardb("cyp2d6", "hg19")
        >>> print(stardb["*2"].score)
        1.0
    """

    p = os.path.dirname(__file__)
    gene_table = read_gene_table(f"{p}/resources/sg/gene_table.txt")
    snp_table = read_snp_table(f"{p}/resources/sg/snp_table.txt", gene_table)
    snpdb = build_snpdb(tg, gb, snp_table)
    star_table = read_star_table(f"{p}/resources/sg/star_table.txt")

    return build_stardb(tg, gb, star_table, snpdb)

def get_gene_table() -> Dict[str, Dict[str, str]]:
    """
    Get gene table object.

    Returns:
        dict[str, dict[str, str]]: Gene table object.
    """

    p = os.path.dirname(__file__)
    return read_gene_table(f"{p}/resources/sg/gene_table.txt")

def get_target_genes() -> List[str]:
    """Get the list of target gene names.

    Returns:
        list[str]: A list of gene names.
    """
    gene_table = get_gene_table()
    return [k for k, v in gene_table.items() if v["type"] == "target"]

def get_target_region(tg: str, gb: str) -> str:
    """Get the genomic region for the target gene.

    Returns:
        str: Genomic region.

    Args:
        tg (str): Target gene.
        gb (str): Genome build (hg19, hg38).
    """
    gene_table = get_gene_table()
    target_genes = [k for k, v in gene_table.items() if v["type"] == "target"]

    if tg not in target_genes:
        raise ValueError(f"'{tg}' is not among target genes: {target_genes}")

    return gene_table[tg][f"{gb}_region"]

def get_file_list(
        td: str,
        fe: Optional[str] = None
    ) -> List[str]:
    """ Get the list of files from the target directory.

    Returns:
        list[str]: List of files.

    Args:
        td (str): Target directory.
        fe (str, optional): File extension.
    """
    result = []
    for r, d, f in os.walk(td):
        for fn in f:
            if fe and not fn.endswith(fe):
                continue
            result.append(os.path.join(r, fn))
    return result

def read_file_list(fl: str) -> List[str]:
    """ Get the list of files from the list file.

        Returns:
            list[str]: List of files.

        Args:
            fl (str): List file.
    """
    result = []
    with open(fl) as f:
        for line in f:
            if not line.strip():
                continue
            result.append(line.strip())
    return result

def randstr(
    chars: str = string.ascii_uppercase + string.digits,
    n: int = 5
) -> str:
    """Generate a random string of length n."""
    first = random.choice(string.ascii_lowercase)
    return first + "".join(random.choice(chars) for _ in range(n))

def temp_env(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "temp_dir" in kwargs and kwargs["temp_dir"]:
            temp_obj = None
            temp_path = os.path.realpath(kwargs["temp_dir"])
        else:
            temp_obj = TemporaryDirectory()
            temp_path = temp_obj.name

        func(*args, **kwargs, temp_path=temp_path)

        if temp_obj:
            temp_obj.cleanup()

    return wrapper

def bam_getter(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if kwargs["bam_file"]:
            input_files = kwargs["bam_file"]
        elif kwargs["bam_dir"]:
            bam_path = os.path.realpath(kwargs["bam_dir"])
            input_files = []
            for r, d, f in os.walk(bam_path):
                for x in f:
                    if x.endswith("bam"):
                        input_files.append(f"{bam_path}/{x}")
        elif kwargs["bam_list"]:
            input_files = []
            with open(kwargs["bam_list"]) as f:
                for line in f:
                    input_files.append(line.strip())
        else:
            input_files = []

        if not input_files:
            raise ValueError("No input BAM files found")

        result = func(*args, **kwargs, input_files=input_files)

        return result

    return wrapper

def get_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s"
    )

    return logging.getLogger()

def conf_env(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger()
        logger.info("Configuration:")

        with open(kwargs["conf_file"]) as f:
            for line in f:
                logger.info("    " + line.strip())

        config = configparser.ConfigParser()
        config.read(kwargs["conf_file"])

        func(*args, **kwargs, config=config)

    return wrapper
