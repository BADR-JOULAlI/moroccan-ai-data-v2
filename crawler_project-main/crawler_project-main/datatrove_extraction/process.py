from datatrove.pipeline.writers.jsonl import JsonlWriter
from datatrove.pipeline.extractors import Trafilatura
from datatrove.executor import LocalPipelineExecutor
from datatrove.utils.typeshelper import Languages
from datatrove.pipeline.tokens import TokensCounter
from datatrove.pipeline.filters import (
    GopherRepetitionFilter, 
)
from datatrove.pipeline.dedup import (
    MinhashDedupSignature,
    MinhashDedupBuckets, 
    MinhashDedupCluster,
    MinhashDedupFilter
)
from datatrove.utils.hashing import HashConfig
from datatrove.pipeline.dedup.minhash import MinhashConfig
from datatrove.pipeline.readers import JsonlReader
from datatrove.pipeline.filters import LambdaFilter

from datatrove.pipeline.inference.run_inference import (
    InferenceConfig,
    InferenceRunner,
    InferenceResult,
)

from helpers.pipeline_utils.postprocess_utils import AddMetadata, DropFailedDocuments, CoallesceFailedPages, RemoveDoclingMetadata

from helpers.filters.GopherQualityFilter_ours import GopherQualityFilter
from helpers.filters.C4QualityFilter_ours import C4QualityFilter
from helpers.filters.ArabicNormalizationFilter import ArabicNormalizationFilter
from helpers.filters.LatinScriptFilter import ArabicScriptFilter
from helpers.extra_helpers.validateInputs import validate_inputs
from helpers.readers.WarcGeneralReader import WarcGeneralReader
from helpers.main_helpers.utils import filter_non_pdf, filter_non_html, get_content_bytes, filter_ocr
from helpers.main_helpers.dedup.exact_dedup import (
    ExactDedupConfig, 
    ExactDedupSignature,
    ExactFindDedups,
    ExactDedupFilter
)
from helpers.postprocessing.boilerplate import TagBoilerplateFormatter
from helpers.postprocessing.normalize import Normalize
from helpers.predictors.ocr_predictor import PDFScannedPredictor
from helpers.extractor.docling import DoclingExtractor
from helpers.pipeline_utils.extract_utils import rollout_extract
from helpers.ocr_helper.ocr_correction import correct_ocr_with_gemma
from pathlib import Path
import argparse
import os
import sys
############ Usages: #########################################################
# run without validation: uv run process.py
# run another segment: uv run process.py --segment segment-2026-07
# run with validation: uv run process.py --validate-warc
# run with validation and auto-repair: uv run process.py --validate-warc --auto-repair
################################################################################

def _segment_from_args(default: str = "segment-2026-01") -> str:
    """Read the segment before global input/output paths are created."""
    segment = os.environ.get("SEGMENT_TO_PROCESS", default)
    for index, arg in enumerate(sys.argv[1:], start=1):
        if arg == "--segment" and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
        if arg.startswith("--segment="):
            return arg.split("=", 1)[1]
    return segment


SEGMENT_TO_PROCESS = _segment_from_args()
PROCESS_HTML = True
STORE_PDF = True
PROCESS_PDF = True

MAIN_OUTPUT_PATH = Path(__file__).parent / "output" / SEGMENT_TO_PROCESS
BASE_PROCESSING = MAIN_OUTPUT_PATH / "base_processing"
BASE_PROCESSING.mkdir(exist_ok=True, parents=True)
input_path = Path(__file__).parent / "input" / SEGMENT_TO_PROCESS
model_cache_path = Path(__file__).parent.parent / "models_cache"

# Set OpenVINO layout model path for the custom LayoutPredictor
os.environ["LAYOUT_VINO_PATH"] = str(model_cache_path / "heron" / "heron_int8_quant.xml")

MINHASH_BASE_PATH = MAIN_OUTPUT_PATH / "minhash"
MINHASH_BASE_PATH.mkdir(exist_ok=True, parents=True)
LOGS_FOLDER=MAIN_OUTPUT_PATH / "logs"
LOGS_FOLDER.mkdir(exist_ok=True, parents=True)

OCR_BASE_PATH = MAIN_OUTPUT_PATH / "ocr"
OCR_BASE_PATH.mkdir(exist_ok=True, parents=True)

# DAta path
html_path = MAIN_OUTPUT_PATH / "data_filtering" / "html"
html_path.mkdir(exist_ok=True, parents=True)
pdfs_path = MAIN_OUTPUT_PATH / "data_filtering" / "pdfs"
pdfs_path.mkdir(exist_ok=True, parents=True)
not_html_or_pdf_path = MAIN_OUTPUT_PATH / "data_filtering" / "not_html_or_pdf"
not_html_or_pdf_path.mkdir(exist_ok=True, parents=True)

FINAL_DATA_PATH = MAIN_OUTPUT_PATH / "final_data"
FINAL_DATA_PATH.mkdir(exist_ok=True, parents=True)

PDF_ALL_POSTPROCESSED = BASE_PROCESSING / "pdfs" / "all_postprocessed"
PDF_ALL_POSTPROCESSED.mkdir(exist_ok=True, parents=True)

# Models path
PDF_SCANNED_MODEL_PATH = model_cache_path / "xgb_ocr_classifier" / "xgb_classifier.ubj"

number_of_tasks = sum(1 for item in input_path.iterdir() if item.is_dir())
# number_of_workers = os.cpu_count() -1 if os.cpu_count() > 1 else 1
number_of_workers_io = 8
number_of_workers_cpu = 6
number_of_workers_heavy = 4
# print(f"Number of tasks: {number_of_tasks}")
# print(f"Number of workers: {number_of_workers}")

# Configure MinHash deduplication
minhash_config = MinhashConfig(
    hash_config=HashConfig(
        hash_fc="sha1",
        precision=64,
    ),
    num_buckets=14,
    hashes_per_bucket=8,
    n_grams=5,
)

# Configure Exact deduplication
CONTENT_DEDUP_CONFIG = ExactDedupConfig(content_getter=get_content_bytes)

def main():

    ############################################## Stage 0: Filtering Stage
    stage0_pipeline = [
        WarcGeneralReader(
            data_folder=str(input_path),
            glob_pattern="*/*.warc.gz",
            default_metadata={"segment":SEGMENT_TO_PROCESS},
            limit=15
        ),
        LambdaFilter(
            filter_non_html,
                exclusion_writer=JsonlWriter(
                    output_folder=str(html_path),
                    compression="zstd",
                    output_filename="html_${rank}.jsonl",
                ),
            ),
    ]
    if STORE_PDF:
        stage0_pipeline.append(
            LambdaFilter(
                filter_non_pdf,
                    exclusion_writer=JsonlWriter(
                            output_folder=str(pdfs_path),
                            compression="zstd",
                            output_filename="pdfs_${rank}.jsonl",
                        ),
                ),
        )
    # stage0_pipeline.append(
    #     JsonlWriter(
    #         output_folder=str(not_html_or_pdf_path),
    #         compression="zstd",
    #         output_filename="not_html_or_pdf_${rank}.jsonl",
    #     ),
    # )

    stage0_executor = LocalPipelineExecutor(
        pipeline=stage0_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage0",
        tasks=number_of_tasks,
        workers=number_of_workers_io
    )

    ############################################## Html Stages ##############################################
    ######### Stage 1: HTML Base Processing Stage
    stage1_html_pipeline = [
        JsonlReader(
            data_folder=str(html_path),
            glob_pattern="*.jsonl.zst",
            doc_progress=True,
        ),
        Trafilatura(favour_precision=True, timeout=30, exclusion_writer=JsonlWriter(f"{BASE_PROCESSING}/html/removed/0_html")),

        ArabicNormalizationFilter(
            exclusion_writer=JsonlWriter(f"{BASE_PROCESSING}/html/removed/1_arabic_norm"),
        ),
        
        GopherRepetitionFilter(              
            exclusion_writer=JsonlWriter(
                f"{BASE_PROCESSING}/html/removed/2_gopher_rep"
            ),
            language=Languages.moroccan_arabic,
            top_n_grams=((2, 0.4), (3, 0.2), (4, 0.2)),
        ),

        GopherQualityFilter(
            exclusion_writer=JsonlWriter(f"{BASE_PROCESSING}/html/removed/3_gopher_qual")
        ),

        C4QualityFilter(
            exclusion_writer=JsonlWriter(f"{BASE_PROCESSING}/html/removed/4_c4_qual"),
        ),

        # FineWebQualityFilter(
        #     exclusion_writer=JsonlWriter(f"{BASE_PROCESSING}/html/removed/5_fineweb_qual/{SEGMENT_TO_PROCESS}")
        # ),

        JsonlWriter(
            output_folder=f"{BASE_PROCESSING}/html/output", # delete html after
            compression="zstd",
            output_filename="html_${rank}.jsonl",
        )
    ]

    stage1_html_executor = LocalPipelineExecutor(
        pipeline=stage1_html_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage1",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu
    )

    ############# Stage 2: Minhash Stage
    stage2_html_pipeline = [
        JsonlReader(f"{BASE_PROCESSING}/html/output"),
        MinhashDedupSignature(
            output_folder=f"{MINHASH_BASE_PATH}/html/signatures",
            config=minhash_config
        ),
    ]

    stage2_html_executor = LocalPipelineExecutor(
        pipeline=stage2_html_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage2",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu
    )

    ############# Stage 3: Minhash Buckets Stage
    stage3_html_pipeline = [
        MinhashDedupBuckets(
            input_folder=f"{MINHASH_BASE_PATH}/html/signatures",
            output_folder=f"{MINHASH_BASE_PATH}/html/buckets",
            config=MinhashConfig(hash_config=minhash_config.hash_config),
        ),
    ]

    stage3_html_executor = LocalPipelineExecutor(
        pipeline=stage3_html_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage3",
        tasks=minhash_config.num_buckets * 1, # it was 25
        workers=number_of_workers_cpu
    )

    ############# Stage 4: Minhash Clustering Stage
    stage4_html_pipeline = [
        MinhashDedupCluster(
            input_folder=f"{MINHASH_BASE_PATH}/html/buckets",
            output_folder=f"{MINHASH_BASE_PATH}/html/remove_ids",
            config=minhash_config,
        ),
    ]

    stage4_html_executor = LocalPipelineExecutor(
        pipeline=stage4_html_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage4",
        tasks=1,
        workers=1
    )

    ############# Stage 5: Minhash Filtering Stage
    stage5_html_pipeline = [
        JsonlReader(f"{BASE_PROCESSING}/html/output"),
        TokensCounter(
            tokenizer_name_or_path=str(model_cache_path / "aragpt2_base_tokenizer" / "tokenizer.json"),
        ),
        MinhashDedupFilter(
            input_folder=f"{MINHASH_BASE_PATH}/html/remove_ids"
        ),
        TokensCounter(
            tokenizer_name_or_path=str(model_cache_path / "aragpt2_base_tokenizer" / "tokenizer.json"),
        ),
        JsonlWriter(
            output_folder=f"{FINAL_DATA_PATH}/html",
            output_filename="final_data_${rank}.jsonl.zst",
            compression="zstd",
        )
    ]

    stage5_html_executor = LocalPipelineExecutor(
        pipeline=stage5_html_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage5",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu
    )

    ############################################## Pdf Stages ##############################################
    ######### Stage 6, 7, and 8: content_dedup_ocr_organize
    stage6_pdf_pipeline = [
        JsonlReader(data_folder=str(pdfs_path), 
            glob_pattern="*.jsonl.zst", 
            doc_progress=True
        ),
        ExactDedupSignature(
            output_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup/signatures",
            config=CONTENT_DEDUP_CONFIG,
        ),
    ]

    stage6_pdf_executor = LocalPipelineExecutor(
        pipeline=stage6_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage6",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu
    )

    stage7_pdf_pipeline = [
        ExactFindDedups(
            data_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup/signatures",
            output_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup/dedups",
            config=CONTENT_DEDUP_CONFIG,
        ),
    ]

    stage7_pdf_executor = LocalPipelineExecutor(
        pipeline=stage7_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage7",
        tasks=1,
        workers=1
    )

    stage8_pdf_pipeline = [
        JsonlReader(str(pdfs_path), 
            glob_pattern="*.jsonl.zst", 
            doc_progress=True),
        ExactDedupFilter(
            data_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup/dedups",
            exclusion_writer=JsonlWriter(f"{MINHASH_BASE_PATH}/pdfs/dedup/removed", compression="zstd"),
            config=CONTENT_DEDUP_CONFIG,
        ),
        PDFScannedPredictor(
            path_to_model=PDF_SCANNED_MODEL_PATH,
            exclusion_writer=JsonlWriter(
                output_folder=f"{OCR_BASE_PATH}/pdfs/failed_ocr_predictor",
                compression="zstd",
                output_filename="failed_ocr_predictor_${rank}.jsonl",
            ),
            exclude_failed=True,
        ),
        LambdaFilter(filter_ocr, 
            exclusion_writer=JsonlWriter(output_folder=f"{OCR_BASE_PATH}/pdfs/scanned_and_DigitalArab_pdfs",
            output_filename="scanned_pdfs_${rank}.jsonl",
            compression="zstd"),
        ),
        ArabicScriptFilter(
            exclusion_writer=JsonlWriter(
                output_folder=f"{OCR_BASE_PATH}/pdfs/scanned_and_DigitalArab_pdfs",
                output_filename="digital_arabic_${rank}.jsonl.zst",
                compression="zstd",
            ),
        ),
        JsonlWriter(output_folder=f"{OCR_BASE_PATH}/pdfs/digital_latin", 
            compression="zstd",
            output_filename="digital_latin_${rank}.jsonl.zst",
        ),
    ]
    
    stage8_pdf_executor = LocalPipelineExecutor(
        pipeline=stage8_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage8",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu
    )
    ############ Stage 9: Extract
    # Non-OCR extraction (Docling)
    stage9_pdf_pipeline = [
        JsonlReader(
                data_folder=str(OCR_BASE_PATH / "pdfs" / "digital_latin"),
                glob_pattern="*.jsonl.zst",
                doc_progress=True,
            ),
        DoclingExtractor(
                timeout=10 * 60,
                exclusion_writer=JsonlWriter(
                    output_folder=str(BASE_PROCESSING / "pdfs" / "docling_failed_extraction"),
                    output_filename="docling_failed_extraction_${rank}.jsonl.zst",
                    compression="zstd",
                ),
            ),
        JsonlWriter(output_folder=str(BASE_PROCESSING / "pdfs" / "docling_extraction"), 
            output_filename="docling_extraction_${rank}.jsonl.zst",
            compression="zstd",
            ),
    ]

    stage9_pdf_executor = LocalPipelineExecutor(
        pipeline=stage9_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage9",
        tasks=number_of_tasks,
        workers=number_of_workers_heavy
    )

    ############ Stage 9b: Docling Post-Processing
    stage9b_pdf_pipeline = [
        JsonlReader(
            data_folder=str(BASE_PROCESSING / "pdfs" / "docling_extraction"),
            glob_pattern="*.jsonl.zst",
            doc_progress=True,
        ),
        AddMetadata(is_docling=True),
        DropFailedDocuments(f"{BASE_PROCESSING}/pdfs/docling_empty_pages"),
        CoallesceFailedPages(f"{BASE_PROCESSING}/pdfs/docling_failed_pages"),
        TagBoilerplateFormatter(is_ocr=False, drop=True),
        Normalize(is_from_docling=True),
        RemoveDoclingMetadata(),
        TokensCounter(
            tokenizer_name_or_path=str(model_cache_path / "aragpt2_base_tokenizer" / "tokenizer.json"),
        ),
        JsonlWriter(
            output_folder=str(PDF_ALL_POSTPROCESSED),
            output_filename="docling_${rank}.jsonl",
            compression="zstd",
        ),
    ]

    stage9b_pdf_executor = LocalPipelineExecutor(
        pipeline=stage9b_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage9b",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu,
    )

    # OCR extraction 
    stage10_pdf_pipeline = [
        JsonlReader(
            data_folder=str(OCR_BASE_PATH / "pdfs" / "scanned_and_DigitalArab_pdfs"),
            glob_pattern="*.jsonl.zst",
            doc_progress=True,
        ),
        # InferenceRunner(
        #     rollout_fn=rollout_extract,
        #     config=InferenceConfig(
        #         model_name_or_path="reducto/RolmOCR",
        #         default_generation_params={"temperature": 0.0},
        #         max_concurrent_generations=300,
        #         server_type="vllm",
        #     ),
        #     output_writer=JsonlWriter(output_folder=str(MINHASH_BASE_PATH / "pdfs" / "ocr_extraction"), compression="zstd"),
        # )

        InferenceRunner(
            rollout_fn=rollout_extract,
            config=InferenceConfig(
                model_name_or_path="/home/skiredj.abderrahman/lina/chandra-ocr-2", # model name on HPC
                server_type="endpoint",
                endpoint_url="http://localhost:9996/",
                default_generation_params={
                    "temperature": 0.0,
                    "max_tokens": 1800,
                },
                max_concurrent_generations=80,
                metric_interval=120,
                request_timeout=300,
            ),
            output_writer=JsonlWriter(
                output_folder=str(OCR_BASE_PATH / "pdfs" / "ocr_extraction"),
                output_filename="ocr_extraction_${rank}_chunk_${chunk_index}.jsonl",  # needs ${chunk_index}
                compression="zstd",
            ),
            checkpoints_local_dir=str(OCR_BASE_PATH / "pdfs" / "ocr_extraction" / ".checkpoints"),
            records_per_chunk=200, # chunk size 
        )
        # # TODO: add ocr extraction here (InferenceRunner requires rollout_fn, config, output_writer)
        # JsonlWriter(output_folder=str(MINHASH_BASE_PATH / "pdfs" / "ocr_extraction"), 
        #     compression="zstd",
        # ),
    ]

    stage10_pdf_executor = LocalPipelineExecutor(
        pipeline=stage10_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage10",
        tasks=1,
        workers=1
    )

    #OCR Correction stage with Gemma (optional, can be run as a separate stage after extraction)
    stage11_pdf_pipeline = [

        JsonlReader(
            data_folder=str(OCR_BASE_PATH / "pdfs" / "ocr_extraction"),
            glob_pattern="*.jsonl.zst",
            doc_progress=True,
        ),
        AddMetadata(is_docling=False),
        DropFailedDocuments(f"{OCR_BASE_PATH}/pdfs/empty_pages"),
        CoallesceFailedPages(f"{OCR_BASE_PATH}/pdfs/failed_pages"),
        TagBoilerplateFormatter(is_ocr=True, drop=True),
        Normalize(is_from_docling=False),
        # LambdaFilter(correct_ocr_with_gemma), # TODO: add ocr correction here
        TokensCounter(
            tokenizer_name_or_path=str(model_cache_path / "aragpt2_base_tokenizer" / "tokenizer.json"),
        ),
        JsonlWriter(
            output_folder=str(PDF_ALL_POSTPROCESSED),
            output_filename="ocr_corrected_${rank}.jsonl",
            compression="zstd",
        ),
    ]

    stage11_pdf_executor = LocalPipelineExecutor(
        pipeline=stage11_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage11",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu
    )

    # Stage 12: Minhash Signatures PDF
    stage12_pdf_pipeline = [
        JsonlReader(
            data_folder=str(PDF_ALL_POSTPROCESSED),
            glob_pattern="*.jsonl.zst",
            doc_progress=True,
        ),
        MinhashDedupSignature(
            output_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup_text/signatures",
            config=minhash_config,
        ),
    ]
    stage12_pdf_executor = LocalPipelineExecutor(
        pipeline=stage12_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage12",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu
    )

    # Stage 13: Minhash Buckets PDF
    stage13_pdf_pipeline = [
        MinhashDedupBuckets(
            input_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup_text/signatures",
            output_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup_text/buckets",
            config=MinhashConfig(hash_config=minhash_config.hash_config),
        ),
    ]
    stage13_pdf_executor = LocalPipelineExecutor(
        pipeline=stage13_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage13",
        tasks=minhash_config.num_buckets,
        workers=number_of_workers_cpu
    )

    # Stage 14: Minhash Clustering PDF
    stage14_pdf_pipeline = [
        MinhashDedupCluster(
            input_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup_text/buckets",
            output_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup_text/remove_ids",
            config=minhash_config,
        ),
    ]
    stage14_pdf_executor = LocalPipelineExecutor(
        pipeline=stage14_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage14",
        tasks=1,
        workers=1
    )

    # Stage 15: Minhash Filter PDF
    stage15_pdf_pipeline = [
        JsonlReader(
            data_folder=str(PDF_ALL_POSTPROCESSED),
            glob_pattern="*.jsonl.zst",
            doc_progress=True,
        ),
        MinhashDedupFilter(
            input_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup_text/remove_ids",
        ),
        TokensCounter(
            tokenizer_name_or_path=str(model_cache_path / "aragpt2_base_tokenizer" / "tokenizer.json"),
        ),
        JsonlWriter(
            output_folder=str(FINAL_DATA_PATH / "pdfs"),
            compression="zstd",
            output_filename="pdfs_${rank}.jsonl.zst",
        )
    ]
    stage15_pdf_executor = LocalPipelineExecutor(
        pipeline=stage15_pdf_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage15",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu
    )

    ############################################## Main Pipeline ##############################################
    try:
        ######################## Filtering Stage ########################
        print("Stage 0: Running filtering stage...")
        stage0_executor.run()

        ######################## Html Stages ########################
        if PROCESS_HTML:
            output_html_files = list(html_path.glob("*.jsonl.zst"))
            if not output_html_files:
                print("No html documents survived filtering — skipping dedup stages.")
                print()
            else:
                print("Stage 1: Running html base processing stage...")
                stage1_html_executor.run()

                print("Stage 2: Running minhash stage...")
                stage2_html_executor.run()

                print("Stage 3: Running minhash buckets stage...")
                stage3_html_executor.run()

                print("Stage 4: Running minhash clustering stage...")
                stage4_html_executor.run()

                print("Stage 5: Running minhash filtering stage...")
                stage5_html_executor.run()

        ######################## Pdf Stages ########################
        if PROCESS_PDF:
            output_pdf_files = list(pdfs_path.glob("*.jsonl.zst"))
            if not output_pdf_files:    
                print("No pdf documents survived filtering — skipping dedup stages.")
                print()
            else:
                print("Stage 6: Running pdf exact deduplication signatures stage...")
                stage6_pdf_executor.run()

                print("Stage 7: Running pdf exact deduplication find dedups stage...")
                stage7_pdf_executor.run()

                print("Stage 8: Running pdf exact deduplication filter stage...")
                stage8_pdf_executor.run()

                output_non_ocr_pdf_files = list((OCR_BASE_PATH / "pdfs" / "digital_latin").glob("*.jsonl.zst"))
                if not output_non_ocr_pdf_files:
                    print("No non-ocr pdf documents survived deduplication — skipping non-ocr extraction stage.")
                    print()
                else:
                    print("Stage 9: Running pdf non-ocr extraction stage...")
                    stage9_pdf_executor.run()

                    output_docling_extracted = list((BASE_PROCESSING / "pdfs" / "docling_extraction").glob("*.jsonl.zst"))
                    if output_docling_extracted:
                        print("Stage 9b: Running docling post-processing stage...")
                        stage9b_pdf_executor.run()

                output_ocr_pdf_files = list((OCR_BASE_PATH / "pdfs" / "scanned_and_DigitalArab_pdfs").glob("*.jsonl.zst"))
                if not output_ocr_pdf_files:
                    print("No ocr pdf documents survived deduplication — skipping ocr extraction stage.")
                    print()
                else:
                    print("Stage 10: Running pdf ocr extraction stage...")
                    stage10_pdf_executor.run()

                output_ocr_extracted_files = list((OCR_BASE_PATH / "pdfs" / "ocr_extraction").glob("*.jsonl.zst"))
                if not output_ocr_extracted_files:
                    print("No ocr extracted pdf documents — skipping ocr correction stage.")
                    print()
                else:
                    print("Stage 11: Running ocr correction stage...")
                    stage11_pdf_executor.run()

                ######################## Minhash Stages ########################
                output_postprocessed_files = list(PDF_ALL_POSTPROCESSED.glob("*.jsonl.zst"))
                if not output_postprocessed_files:
                    print("No post-processed pdf documents — skipping minhash dedup stages.")
                    print()
                else:
                    print("Stage 12: Running minhash stage...")
                    stage12_pdf_executor.run()

                    print("Stage 13: Running minhash buckets stage...")
                    stage13_pdf_executor.run()

                    print("Stage 14: Running minhash clustering stage...")
                    stage14_pdf_executor.run()

                    print("Stage 15: Running minhash filter stage...")
                    stage15_pdf_executor.run()
        
        print("Pipeline completed successfully!")
        
    except Exception as e:
        print(f"Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == '__main__':
    # Parse command-line arguments (only in main process)
    parser = argparse.ArgumentParser(
        description='Extract text from WARC files using datatrove pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Examples:
    # Run without WARC validation
    uv run process.py

    # Run a specific segment
    uv run process.py --segment segment-2026-07
    
    # Validate WARC files before processing (report issues, don't repair)
    uv run process.py --validate-warc
    
    # Validate and automatically repair invalid WARC files
    uv run process.py --validate-warc --auto-repair
            """
    )
    parser.add_argument(
        '--segment',
        default=SEGMENT_TO_PROCESS,
        help='Input/output segment to process (default: SEGMENT_TO_PROCESS env var or segment-2026-01)'
    )
    parser.add_argument(
        '--validate-warc',
        action='store_true',
        help='Validate WARC file integrity before processing'
    )
    parser.add_argument(
        '--auto-repair',
        action='store_true',
        help='Automatically repair invalid WARC files (requires --validate-warc)'
    )
    args = parser.parse_args()
    
    # Validate inputs (with optional WARC validation) - only runs in main process
    try:
        validate_inputs(
            validate_warc=args.validate_warc,
            auto_repair=args.auto_repair,
            segment=SEGMENT_TO_PROCESS
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"Validation error: {e}")
        raise Exception("Validation error: " + str(e))
    
    main()
