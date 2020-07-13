import configparser
import os

from .common import logging, LINE_BREAK1, is_chr, get_gene_table

logger = logging.getLogger(__name__)

def sgep(conf: str) -> None:
    """
    Run per-project genotyping with Stargazer (1).

    Args:
        conf (str): Configuration file.

    This is what a typical configuration file for ``sgep`` looks like:

        .. code-block:: python

            # File: example_conf.txt
            # Do not make any changes to this section.
            [DEFAULT]
            mapping_quality = 1
            output_prefix = pypgx
            control_gene = NONE
            qsub_options = NONE

            # Make any necessary changes to this section.
            [USER]
            fasta_file = reference.fa
            manifest_file = manifest.txt
            project_path = /path/to/project/
            target_gene = cyp2d6
            genome_build = hg19
            data_type = wgs
            dbsnp_file = dbsnp.vcf
            stargazer_tool = Stargazer_v1.0.9
            gatk_tool = GenomeAnalysisTK.jar
            control_gene = vdr
            qsub_options = -V -l mem_requested=10G

    This table summarizes the configuration parameters specific to ``sgep``:

        .. list-table::
           :widths: 25 75
           :header-rows: 1

           * - Parameter
             - Summary
           * - control_gene
             - Control gene or region.
           * - data_type
             - Data type (wgs, ts, chip).
           * - dbsnp_file
             - dbSNP VCF file.
           * - fasta_file
             - Reference FASTA file.
           * - gatk_tool
             - GATK program.
           * - genome_build
             - Genome build (hg19, hg38).
           * - manifest_file
             - Manifest file.
           * - mapping_quality
             - Minimum mapping quality for read depth.
           * - output_prefix
             - Output prefix.
           * - project_path
             - Output project directory.
           * - qsub_options
             - Options for qsub command.
           * - stargazer_tool
             - Stargazer program.
           * - target_gene
             - Target gene.
    """

    gene_table = get_gene_table()

    # Log the configuration data.
    logger.info(LINE_BREAK1)
    logger.info("Configureation:")
    with open(conf) as f:
        for line in f:
            logger.info("    " + line.strip())
    logger.info(LINE_BREAK1)

    # Read the configuration file.
    config = configparser.ConfigParser()
    config.read(conf)

    # Parse the configuration data.
    mapping_quality = config["USER"]["mapping_quality"]
    output_prefix = config["USER"]["output_prefix"]
    genome_build = config["USER"]["genome_build"]
    manifest_file = config["USER"]["manifest_file"]
    project_path = os.path.realpath(config["USER"]["project_path"])
    fasta_file = config["USER"]["fasta_file"]
    target_gene = config["USER"]["target_gene"]
    control_gene = config["USER"]["control_gene"]
    data_type = config["USER"]["data_type"]
    dbsnp_file = config["USER"]["dbsnp_file"]
    stargazer_tool = config["USER"]["stargazer_tool"]
    gatk_tool = config["USER"]["gatk_tool"]
    qsub_options = config["USER"]["qsub_options"]

    # Read the manifest file.
    bam_files = {}
    with open(manifest_file) as f:
        header = next(f).strip().split("\t")
        i1 = header.index("sample_id")
        i2 = header.index("bam")
        for line in f:
            fields = line.strip().split("\t")
            sample_id = fields[i1]
            bam = fields[i2]
            bam_files[sample_id] = bam

    # Log the number of samples.
    logger.info(f"Number of samples: {len(bam_files)}")

    # Make the project directories.
    os.mkdir(project_path)
    os.mkdir(f"{project_path}/shell")
    os.mkdir(f"{project_path}/log")
    os.mkdir(f"{project_path}/temp")

    t = [is_chr(v) for k, v in bam_files.items()]
    if all(t):
        chr_str = "chr"
    elif not any(t):
        chr_str = ""
    else:
        raise ValueError("Mixed types of SN tags found.")

    target_region = gene_table[target_gene][f"{genome_build}_region"].replace("chr", "")

    if control_gene != "NONE":
        # Write the shell script for bam2gdf.
        s = f"pypgx bam2gdf {genome_build} {target_gene} {control_gene} \\\n"

        for sample_id in bam_files:
            s += f"  {bam_files[sample_id]} \\\n"

        s += f"  -o {project_path}/{output_prefix}.gdf\n"

        with open(f"{project_path}/shell/doc.sh", "w") as f:
            f.write(s)

    # Write the shell script for HaplotypeCaller.
    for sample_id in bam_files:
        s = (
            f"project={project_path}\n"
            f"gatk={gatk_tool}\n"
            f"fasta={fasta_file}\n"
            f"dbsnp={dbsnp_file}\n"
            f"bam={bam_files[sample_id]}\n"
            f"gvcf=$project/temp/{sample_id}.g.vcf\n"
            "\n"
            f"java -jar $gatk -T HaplotypeCaller \\\n"
            "  -R $fasta \\\n"
            "  -D $dbsnp \\\n"
            "  --emitRefConfidence GVCF \\\n"
            "  -U ALLOW_SEQ_DICT_INCOMPATIBILITY \\\n"
            "  -I $bam \\\n"
            "  -o $gvcf \\\n"
            f"  -L {chr_str}{target_region}\n"
        )

        with open(f"{project_path}/shell/hc-{sample_id}.sh", "w") as f:
            f.write(s)

    # Write the shell script for post-HaplotypeCaller.
    s = (
        f"project={project_path}\n"
        f"gatk={gatk_tool}\n"
        f"fasta={fasta_file}\n"
        f"dbsnp={dbsnp_file}\n"
        f"vcf1=$project/temp/{output_prefix}.joint.vcf\n"
        f"vcf2=$project/{output_prefix}.joint.filtered.vcf\n"
        "\n"
        f"java -jar $gatk -T GenotypeGVCFs \\\n"
        "  -R $fasta \\\n"
        "  -D $dbsnp \\\n"
        f"  -L {chr_str}{target_region} \\\n"
    )

    for sample_id in bam_files:
        s += f"  --variant $project/temp/{sample_id}.g.vcf \\\n"

    s += (
        "  -o $vcf1 \n"
        "\n"
        f"java -jar $gatk -T VariantFiltration \\\n"
        "  -R $fasta \\\n"
        "  --filterExpression 'QUAL <= 50.0' \\\n"
        "  --filterName QUALFilter \\\n"
        "  --variant $vcf1 \\\n"
        f"  -L {chr_str}{target_region} \\\n"
        "  -o $vcf2\n"
    )

    with open(f"{project_path}/shell/post.sh", "w") as f:
        f.write(s)

    # Write the shell script for Stargazer.
    s = (
        f"project={project_path}\n"
        f"stargazer={stargazer_tool}\n"
        f"vcf=$project/{output_prefix}.joint.filtered.vcf\n"
        "\n"
        f"python3 $stargazer \\\n"
        f"  {data_type} \\\n"
        f"  {genome_build} \\\n"
        f"  {target_gene} \\\n"
        "  $vcf \\\n"
        "  $project/stargazer \\\n"
    )

    if control_gene != "NONE":
        s += (
            f"  --cg {control_gene} \\\n"
            f"  --gdf $project/{output_prefix}.gdf \\\n"
        )

    with open(f"{project_path}/shell/rs.sh", "w") as f:
        f.write(s)

    # Write the shell script for qsub.
    q = "qsub -e $p/log -o $p/log"

    if qsub_options != "NONE":
        q += f" {qsub_options}"

    s = (
        f"p={project_path}\n"
        "\n"
    )

    if control_gene != "NONE":
        s += f"{q} -N doc $p/shell/doc.sh\n"

    for sample_id in bam_files:
        s += f"{q} -N hc $p/shell/hc-{sample_id}.sh\n"

    s += f"{q} -hold_jid hc -N post $p/shell/post.sh\n"

    if control_gene == "NONE":
        s += f"{q} -hold_jid post -N rs $p/shell/rs.sh\n"

    else:
        s += f"{q} -hold_jid doc,post -N rs $p/shell/rs.sh\n"

    with open(f"{project_path}/example-qsub.sh", "w") as f:
        f.write(s)
