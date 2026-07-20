import logging
from typing import TYPE_CHECKING, Callable, Literal

from datatrove.io import DataFileLike, DataFolderLike
from datatrove.pipeline.readers.base import BaseDiskReader


if TYPE_CHECKING:
    from warcio.recordloader import ArcWarcRecord


# Configurer le logger pour la détection PDF/HTML
def setup_content_logger(log_file: str = "warc_content_detection.log"):
    """Configure le logger pour la détection de contenu"""
    logger = logging.getLogger('warc_content_detection')
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.propagate = False
    
    return logger


# Logger global
CONTENT_LOGGER = setup_content_logger()


# Compteurs globaux pour les statistiques
class WarcStats:
    """Classe pour stocker les statistiques de traitement"""
    def __init__(self):
        self.total_records = 0
        self.pdf_count = 0
        self.html_count = 0
        self.unknown_count = 0
        self.metadata_incomplete = 0
        self.mime_type_counts = {}  # Compteur par type MIME
    
    def reset(self):
        """Réinitialiser tous les compteurs"""
        self.total_records = 0
        self.pdf_count = 0
        self.html_count = 0
        self.unknown_count = 0
        self.metadata_incomplete = 0
        self.mime_type_counts = {}
    
    def add_mime_type(self, mime_type):
        """Compter les occurrences de chaque type MIME"""
        if mime_type:
            # Simplifier le type MIME (ex: image/jpeg → image)
            main_type = mime_type.split('/')[0]
            self.mime_type_counts[main_type] = self.mime_type_counts.get(main_type, 0) + 1
    
    def log_summary(self, logger, filepath=None):
        """Logger le résumé des statistiques"""
        logger.info("")
        logger.info("=" * 80)
        logger.info("RÉSUMÉ DES STATISTIQUES")
        if filepath:
            logger.info(f"Fichier: {filepath}")
        logger.info("=" * 80)
        logger.info(f"Total de records traités    : {self.total_records}")
        logger.info(f"  - PDFs détectés           : {self.pdf_count} ({self._percentage(self.pdf_count)}%)")
        logger.info(f"  - HTMLs détectés          : {self.html_count} ({self._percentage(self.html_count)}%)")
        logger.info(f"  - Autres/Inconnus         : {self.unknown_count} ({self._percentage(self.unknown_count)}%)")
        logger.info(f"  - Métadonnées incomplètes : {self.metadata_incomplete}")
        
        # Afficher le détail des types MIME
        if self.mime_type_counts:
            logger.info("")
            logger.info("Détail des types MIME :")
            # Trier par nombre décroissant
            for mime_type, count in sorted(self.mime_type_counts.items(), key=lambda x: x[1], reverse=True):
                percentage = round((count / self.total_records) * 100, 2)
                logger.info(f"  - {mime_type:20s} : {count:4d} ({percentage}%)")
        
        logger.info("=" * 80)
        logger.info("")
    
    def _percentage(self, count):
        """Calculer le pourcentage"""
        if self.total_records == 0:
            return 0.0
        return round((count / self.total_records) * 100, 2)


# Instance globale des statistiques
WARC_STATS = WarcStats()


def is_pdf(content_bytes: bytes, mime_type: str = None) -> bool:
    """
    Vérifie si le contenu est un PDF.
    
    Args:
        content_bytes: Le contenu en bytes
        mime_type: Le type MIME du contenu (optionnel)
    
    Returns:
        bool: True si c'est un PDF, False sinon
    """
    # Vérifier le type MIME
    if mime_type and 'application/pdf' in mime_type.lower():
        return True
    
    # Vérifier la signature PDF (magic bytes: %PDF)
    if content_bytes and len(content_bytes) >= 4:
        if content_bytes[:4] == b'%PDF':
            return True
    
    return False


class WarcReader(BaseDiskReader):
    """Read data from WARC files.
        Will read each record as a separate document.

    Args:
        data_folder: a str, tuple or DataFolder object representing a path/filesystem
        paths_file: optionally provide a file with one path per line (without the `data_folder` prefix) to read.
        compression: the compression to use (default: "infer")
        limit: limit the number of documents to read. Useful for debugging
        skip: skip the first n rows
        file_progress: show progress bar for files
        doc_progress: show progress bar for documents
        adapter: function to adapt the data dict from the source to a Document.
            Takes as input: (self, data: dict, path: str, id_in_file: int | str)
                self allows access to self.text_key and self.id_key
            Returns: a dict with at least a "text" and "id" keys
        text_key: the key containing the text data (default: "text").
        id_key: the key containing the id for each sample (default: "id").
        default_metadata: a dictionary with any data that should be added to all samples' metadata
        recursive: whether to search files recursively. Ignored if paths_file is provided
        glob_pattern: pattern that all files must match exactly to be included (relative to data_folder). Ignored if paths_file is provided
        shuffle_files: shuffle the files within the returned shard. Mostly used for data viz. purposes, do not use with dedup blocks
    """

    name = "🕷 Warc"
    _requires_dependencies = ["warcio", ("cchardet", "faust-cchardet"), ("magic", "python-magic")]

    def __init__(
        self,
        data_folder: DataFolderLike,
        paths_file: DataFileLike | None = None,
        compression: Literal["infer", "gzip", "zstd"] | None = "infer",
        limit: int = -1,
        skip: int = 0,
        file_progress: bool = False,
        doc_progress: bool = False,
        adapter: Callable = None,
        text_key: str = "text",
        id_key: str = "id",
        default_metadata: dict = None,
        recursive: bool = True,
        glob_pattern: str | None = None,
        shuffle_files: bool = False,
    ):
        self.compression = compression
        super().__init__(
            data_folder,
            paths_file,
            limit,
            skip,
            file_progress,
            doc_progress,
            adapter,
            text_key,
            id_key,
            default_metadata,
            recursive,
            glob_pattern,
            shuffle_files,
        )

    def read_file(self, filepath: str):
        from warcio.archiveiterator import ArchiveIterator

        # Réinitialiser les statistiques au début du fichier
        WARC_STATS.reset()
        CONTENT_LOGGER.info("")
        CONTENT_LOGGER.info("=" * 80)
        CONTENT_LOGGER.info(f"DÉBUT DU TRAITEMENT: {filepath}")
        CONTENT_LOGGER.info("=" * 80)
        CONTENT_LOGGER.info("")

        with self.data_folder.open(filepath, "rb", compression=self.compression) as f:
            for ri, record in enumerate(ArchiveIterator(f)):
                with self.track_time():
                    extracted_data = process_record(record)
                    if not extracted_data:
                        continue
                    document = self.get_document_from_dict(extracted_data, filepath, ri)
                    if not document:
                        continue
                yield document
        
        # Logger le résumé à la fin du fichier
        WARC_STATS.log_summary(CONTENT_LOGGER, filepath)


def process_record(record: "ArcWarcRecord") -> dict | None:
    """Process a WARC record to extract the html and metadata (id, url, date)."""
    import cchardet
    import magic

    # record type
    if record.rec_type != "response" and record.rec_type != "conversion":  # wet files have "conversion" type
        return

    # Incrémenter le compteur total
    WARC_STATS.total_records += 1

    # Récupérer les métadonnées
    id_ = record.rec_headers["WARC-Record-ID"]
    url = record.rec_headers.get("WARC-Target-URI", None)
    date = record.rec_headers.get("WARC-Date", None)
    
    # handle older formats
    if not url:
        url = dict(record.rec_headers.headers).get("uri", None)
    if not date:
        date = dict(record.rec_headers.headers).get("archive-date", None)
    
    # Logger si URL ou date inconnue
    if not url or not date:
        WARC_STATS.metadata_incomplete += 1
        CONTENT_LOGGER.warning("MÉTADONNÉES INCOMPLÈTES")
        CONTENT_LOGGER.warning(f"  URL: {url if url else 'INCONNUE'}")
        CONTENT_LOGGER.warning(f"  Date: {date if date else 'INCONNUE'}")
        CONTENT_LOGGER.warning(f"  WARC-Record-ID: {id_}")
        CONTENT_LOGGER.warning("-" * 80)

    # content type filtering
    mime_type = record.rec_headers.get("WARC-Identified-Payload-Type", None)
    
    # Lire le contenu AVANT le filtrage pour pouvoir détecter les PDFs
    content_bytes = record.content_stream().read()
    
    # Si pas de mime_type, utiliser magic pour le détecter
    if mime_type is None:
        # fallback for older crawls without payload types
        mime_type = magic.from_buffer(content_bytes, mime=True)
    
    # Comptabiliser le type MIME
    WARC_STATS.add_mime_type(mime_type)
    
    # ========== DÉTECTION PDF ==========
    if is_pdf(content_bytes, mime_type):
        # Incrémenter le compteur PDF
        WARC_STATS.pdf_count += 1
        
        # Logger les informations du PDF
        CONTENT_LOGGER.info("PDF DÉTECTÉ")
        CONTENT_LOGGER.info(f"  URL: {url if url else 'INCONNUE'}")
        CONTENT_LOGGER.info(f"  WARC-Record-ID: {id_}")
        CONTENT_LOGGER.info(f"  Date: {date if date else 'INCONNUE'}")
        CONTENT_LOGGER.info(f"  Content-Type: {mime_type}")
        CONTENT_LOGGER.info(f"  Taille: {len(content_bytes)} bytes")
        CONTENT_LOGGER.info("-" * 80)
        
        # Ne pas traiter les PDFs
        return None
    
    # ========== FILTRAGE HTML ==========
    # Vérifier si c'est un type HTML valide
    is_html = False
    if mime_type is not None:
        if (mime_type == "text/html" or 
            mime_type == "application/xhtml+xml" or 
            (record.rec_type == "conversion" and mime_type == "text/plain")):
            is_html = True
    
    # Si ce n'est pas du HTML, ignorer
    if not is_html:
        # Incrémenter le compteur unknown
        WARC_STATS.unknown_count += 1
        
        # ========== LOGGER LES AUTRES TYPES ==========
        CONTENT_LOGGER.info("AUTRE TYPE DÉTECTÉ")
        CONTENT_LOGGER.info(f"  URL: {url if url else 'INCONNUE'}")
        CONTENT_LOGGER.info(f"  WARC-Record-ID: {id_}")
        CONTENT_LOGGER.info(f"  Date: {date if date else 'INCONNUE'}")
        CONTENT_LOGGER.info(f"  Content-Type: {mime_type}")
        CONTENT_LOGGER.info(f"  Taille: {len(content_bytes)} bytes")
        CONTENT_LOGGER.info("-" * 80)
        
        return

    # ========== LOGGER HTML DÉTECTÉ ==========
    # Incrémenter le compteur HTML
    WARC_STATS.html_count += 1
    
    CONTENT_LOGGER.info("HTML DÉTECTÉ")
    CONTENT_LOGGER.info(f"  URL: {url if url else 'INCONNUE'}")
    CONTENT_LOGGER.info(f"  WARC-Record-ID: {id_}")
    CONTENT_LOGGER.info(f"  Date: {date if date else 'INCONNUE'}")
    CONTENT_LOGGER.info(f"  Content-Type: {mime_type}")
    CONTENT_LOGGER.info(f"  Taille: {len(content_bytes)} bytes")
    CONTENT_LOGGER.info("-" * 80)

    # Decode the response bytes
    charset = "UTF-8"
    try:
        html = content_bytes.decode(charset)
    except UnicodeDecodeError:
        encoding_det = cchardet.detect(content_bytes)["encoding"]
        if not encoding_det or encoding_det == charset:
            return
        charset = encoding_det

        try:
            html = content_bytes.decode(charset)
        except (UnicodeDecodeError, LookupError):
            return

    return {"text": html, "id": id_, "url": url, "date": date}