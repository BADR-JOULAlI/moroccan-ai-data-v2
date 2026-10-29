"""Configurable extraction entry point; help and preflight need no PDF models."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

if __package__:
    from .runtime_config import ExtractionConfig, load_config
else:
    from runtime_config import ExtractionConfig, load_config


def missing_dependencies(mode: str, word_tokenizer: str = "spacy") -> list[str]:
    modules = ["datatrove", "warcio", "trafilatura", "tokenizers", "orjson", "zstandard", "numpy", "cchardet"]
    if word_tokenizer == "spacy":
        modules.append("spacy")
    if mode == "full":
        modules += ["pymupdf", "xgboost", "openvino", "docling", "transformers", "pandas"]
    return [f"Python dependency missing: {name}" for name in modules if importlib.util.find_spec(name) is None]


def _run_pipeline(config: ExtractionConfig) -> None:
    # Legacy helpers are imported only after a successful preflight. Keep the
    # script and package entry points compatible with those absolute imports.
    extraction_root = str(Path(__file__).resolve().parent)
    if extraction_root not in sys.path:
        sys.path.insert(0, extraction_root)
    from datatrove.pipeline.writers.jsonl import JsonlWriter
    from datatrove.executor import LocalPipelineExecutor
    from datatrove.utils.typeshelper import Languages
    from datatrove.pipeline.tokens import TokensCounter
    from datatrove.pipeline.filters import GopherRepetitionFilter, LambdaFilter
    from datatrove.pipeline.dedup import (
        MinhashDedupSignature, MinhashDedupBuckets, MinhashDedupCluster, MinhashDedupFilter,
    )
    from datatrove.utils.hashing import HashConfig
    from datatrove.pipeline.dedup.minhash import MinhashConfig
    from datatrove.pipeline.readers import JsonlReader
    from helpers.filters.GopherQualityFilter_ours import GopherQualityFilter
    from helpers.filters.C4QualityFilter_ours import C4QualityFilter
    from helpers.filters.ArabicNormalizationFilter import ArabicNormalizationFilter
    from helpers.readers.WarcGeneralReader import build_segment_reader
    from helpers.main_helpers.utils import filter_non_html, filter_non_pdf
    from helpers.extractor.html import HtmlTextExtractor
    from helpers.pipeline_utils.word_tokenizer import UnicodeWordTokenizer

    word_profile = UnicodeWordTokenizer() if config.word_tokenizer == "unicode" else None
    filter_language = word_profile if word_profile is not None else Languages.moroccan_arabic

    SEGMENT_TO_PROCESS = config.segment
    PROCESS_HTML = True
    PROCESS_PDF = config.mode == "full"
    STORE_PDF = PROCESS_PDF
    input_path = config.input_dir
    MAIN_OUTPUT_PATH = config.output_dir
    BASE_PROCESSING = MAIN_OUTPUT_PATH / "base_processing"
    MINHASH_BASE_PATH = MAIN_OUTPUT_PATH / "minhash"
    LOGS_FOLDER = MAIN_OUTPUT_PATH / "logs"
    OCR_BASE_PATH = MAIN_OUTPUT_PATH / "ocr"
    html_path = MAIN_OUTPUT_PATH / "data_filtering" / "html"
    pdfs_path = MAIN_OUTPUT_PATH / "data_filtering" / "pdfs"
    FINAL_DATA_PATH = MAIN_OUTPUT_PATH / "final_data"
    PDF_ALL_POSTPROCESSED = BASE_PROCESSING / "pdfs" / "all_postprocessed"
    PDF_SCANNED_MODEL_PATH = config.pdf_classifier_path
    for path in (BASE_PROCESSING, MINHASH_BASE_PATH, LOGS_FOLDER, html_path, FINAL_DATA_PATH):
        path.mkdir(parents=True, exist_ok=True)
    (MAIN_OUTPUT_PATH / "run_config.json").write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8",
    )
    if PROCESS_PDF:
        for path in (OCR_BASE_PATH, pdfs_path, PDF_ALL_POSTPROCESSED):
            path.mkdir(parents=True, exist_ok=True)
        os.environ["LAYOUT_VINO_PATH"] = str(config.layout_model_path)
    number_of_tasks = len(list(input_path.glob("*/*.warc.gz")))
    number_of_workers_io = min(config.workers_io, number_of_tasks)
    number_of_workers_cpu = config.workers_cpu
    number_of_workers_heavy = config.workers_heavy
    minhash_config = MinhashConfig(
        hash_config=HashConfig(hash_fc="sha1", precision=64),
        num_buckets=14, hashes_per_bucket=8, n_grams=5,
    )


    ############################################## Stage 0: Filtering Stage
    stage0_pipeline = [
        build_segment_reader(
            data_folder=str(input_path),
            segment=SEGMENT_TO_PROCESS,
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
        start_method="spawn",
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
        HtmlTextExtractor(favour_precision=True, timeout=30, exclusion_writer=JsonlWriter(f"{BASE_PROCESSING}/html/removed/0_html")),

        ArabicNormalizationFilter(
            exclusion_writer=JsonlWriter(f"{BASE_PROCESSING}/html/removed/1_arabic_norm"),
        ),

        GopherRepetitionFilter(
            exclusion_writer=JsonlWriter(
                f"{BASE_PROCESSING}/html/removed/2_gopher_rep"
            ),
            language=filter_language,
            top_n_grams=((2, 0.4), (3, 0.2), (4, 0.2)),
        ),

        GopherQualityFilter(
            language=filter_language,
            exclusion_writer=JsonlWriter(f"{BASE_PROCESSING}/html/removed/3_gopher_qual")
        ),

        C4QualityFilter(
            language=filter_language,
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
        start_method="spawn",
        pipeline=stage1_html_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage1",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu
    )

    ############# Stage 2: Minhash Stage
    stage2_html_pipeline = [
        JsonlReader(f"{BASE_PROCESSING}/html/output"),
        MinhashDedupSignature(
            language=word_profile if word_profile is not None else Languages.english,
            output_folder=f"{MINHASH_BASE_PATH}/html/signatures",
            config=minhash_config
        ),
    ]

    stage2_html_executor = LocalPipelineExecutor(
        start_method="spawn",
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
        start_method="spawn",
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
        start_method="spawn",
        pipeline=stage4_html_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage4",
        tasks=1,
        workers=1
    )

    ############# Stage 5: Minhash Filtering Stage
    stage5_html_pipeline = [
        JsonlReader(f"{BASE_PROCESSING}/html/output"),
        TokensCounter(
            tokenizer_name_or_path=str(config.tokenizer_path),
        ),
        MinhashDedupFilter(
            input_folder=f"{MINHASH_BASE_PATH}/html/remove_ids"
        ),
        TokensCounter(
            tokenizer_name_or_path=str(config.tokenizer_path),
        ),
        JsonlWriter(
            output_folder=f"{FINAL_DATA_PATH}/html",
            output_filename="final_data_${rank}.jsonl.zst",
            compression="zstd",
        )
    ]

    stage5_html_executor = LocalPipelineExecutor(
        start_method="spawn",
        pipeline=stage5_html_pipeline,
        logging_dir=f"{LOGS_FOLDER}/stage5",
        tasks=number_of_tasks,
        workers=number_of_workers_cpu
    )

    if PROCESS_PDF:
        from datatrove.pipeline.inference.run_inference import InferenceConfig, InferenceRunner
        from helpers.pipeline_utils.postprocess_utils import (
            AddMetadata, DropFailedDocuments, CoallesceFailedPages, RemoveDoclingMetadata,
        )
        from helpers.filters.LatinScriptFilter import ArabicScriptFilter
        from helpers.main_helpers.utils import get_content_bytes, filter_ocr
        from helpers.main_helpers.dedup.exact_dedup import (
            ExactDedupConfig, ExactDedupSignature, ExactFindDedups, ExactDedupFilter,
        )
        from helpers.postprocessing.boilerplate import TagBoilerplateFormatter
        from helpers.postprocessing.normalize import Normalize
        from helpers.predictors.ocr_predictor import PDFScannedPredictor
        from helpers.extractor.docling import DoclingExtractor
        from helpers.pipeline_utils.extract_utils import rollout_extract
        CONTENT_DEDUP_CONFIG = ExactDedupConfig(content_getter=get_content_bytes)

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
            start_method="spawn",
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
            start_method="spawn",
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
            start_method="spawn",
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
                    artifacts_path=config.model_cache,
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
            start_method="spawn",
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
                tokenizer_name_or_path=str(config.tokenizer_path),
            ),
            JsonlWriter(
                output_folder=str(PDF_ALL_POSTPROCESSED),
                output_filename="docling_${rank}.jsonl",
                compression="zstd",
            ),
        ]

        stage9b_pdf_executor = LocalPipelineExecutor(
            start_method="spawn",
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
                    model_name_or_path=config.ocr_model,
                    server_type="endpoint",
                    endpoint_url=config.ocr_endpoint,
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
            start_method="spawn",
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
                tokenizer_name_or_path=str(config.tokenizer_path),
            ),
            JsonlWriter(
                output_folder=str(PDF_ALL_POSTPROCESSED),
                output_filename="ocr_corrected_${rank}.jsonl",
                compression="zstd",
            ),
        ]

        stage11_pdf_executor = LocalPipelineExecutor(
            start_method="spawn",
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
                language=word_profile if word_profile is not None else Languages.english,
                output_folder=f"{MINHASH_BASE_PATH}/pdfs/dedup_text/signatures",
                config=minhash_config,
            ),
        ]
        stage12_pdf_executor = LocalPipelineExecutor(
            start_method="spawn",
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
            start_method="spawn",
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
            start_method="spawn",
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
                tokenizer_name_or_path=str(config.tokenizer_path),
            ),
            JsonlWriter(
                output_folder=str(FINAL_DATA_PATH / "pdfs"),
                compression="zstd",
                output_filename="pdfs_${rank}.jsonl.zst",
            )
        ]
        stage15_pdf_executor = LocalPipelineExecutor(
            start_method="spawn",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract a configured WARC segment (HTML or full PDF/OCR).")
    parser.add_argument("--config", type=Path, help="JSON configuration; relative paths resolve beside this file")
    parser.add_argument("--segment")
    parser.add_argument("--mode", choices=["html", "full"])
    parser.add_argument("--word-tokenizer", choices=["spacy", "unicode"])
    for name in ("input_dir", "output_dir", "model_cache", "tokenizer_path", "pdf_classifier_path", "layout_model_path"):
        parser.add_argument("--" + name.replace("_", "-"), dest=name)
    parser.add_argument("--ocr-model")
    parser.add_argument("--ocr-endpoint")
    for name in ("workers_io", "workers_cpu", "workers_heavy"):
        parser.add_argument("--" + name.replace("_", "-"), dest=name, type=int)
    parser.add_argument("--check-only", action="store_true", help="Report prerequisites without creating output or contacting a server")
    parser.add_argument("--validate-warc", action="store_true")
    parser.add_argument("--auto-repair", action="store_true", help="Repair WARC files with backups; requires --validate-warc")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows redirected consoles may default to a code page unable to print
    # Arabic diagnostics or Datatrove's status symbols.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.auto_repair and not args.validate_warc:
        parser.error("--auto-repair requires --validate-warc")
    overrides = {key: value for key, value in vars(args).items() if value is not None and key not in {"config", "check_only", "validate_warc", "auto_repair"}}
    try:
        config = load_config(args.config, overrides)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"ready": False, "errors": [str(exc)]}, ensure_ascii=False), file=sys.stderr)
        return 2
    errors = config.check_prerequisites() + missing_dependencies(config.mode, config.word_tokenizer)
    try:
        if config.output_dir.is_dir() and any(config.output_dir.iterdir()):
            previous = config.output_dir / "run_config.json"
            try:
                stored = json.loads(previous.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                stored = None
            if stored != config.to_dict():
                errors.append("Output directory contains a different or untracked run; choose a new --output-dir.")
    except OSError as exc:
        errors.append(f"Cannot inspect output directory: {exc}")
    report = {"ready": not errors, "configuration": config.to_dict(), "errors": errors, "server_contacted": False}
    if args.check_only or errors:
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stdout if args.check_only else sys.stderr)
        return 2 if errors else 0
    try:
        if args.validate_warc:
            if __package__:
                from .helpers.extra_helpers.validateInputs import validate_inputs
            else:
                from helpers.extra_helpers.validateInputs import validate_inputs
            validate_inputs(
                validate_warc=True, auto_repair=args.auto_repair,
                input_dir=config.input_dir,
            )
        _run_pipeline(config)
    except Exception as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if os.name == "nt" and not sys.flags.utf8_mode:
        # Fsspec and Datatrove open JSONL/log files using Python's default
        # encoding. Configure the interpreter before any pipeline work starts,
        # including spawned workers, rather than just reconfiguring stdout.
        import subprocess
        environment = {**os.environ, "PYTHONUTF8": "1"}
        flags = ["-S"] if sys.flags.no_site else []
        raise SystemExit(subprocess.call(
            [sys.executable, "-X", "utf8", *flags, str(Path(__file__).resolve()), *sys.argv[1:]],
            env=environment,
        ))
    raise SystemExit(main())
