"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

export type PdfFitMode = "width" | "page" | "custom";

interface PdfPagePreviewProps {
  file: File;
  pageNumber: number;
  zoom: number;
  fitMode: PdfFitMode;
  onPageCountChange: (pageCount: number) => void;
}

interface ViewportSize {
  width: number;
  height: number;
}

export function PdfPagePreview({
  file,
  pageNumber,
  zoom,
  fitMode,
  onPageCountChange,
}: PdfPagePreviewProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [viewportSize, setViewportSize] = useState<ViewportSize>({
    width: 0,
    height: 0,
  });
  const [pageAspect, setPageAspect] = useState(0.773);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setViewportSize({ width, height });
    });
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  const renderedWidth = useMemo(() => {
    const availableWidth = Math.max(viewportSize.width - 32, 280);
    const availableHeight = Math.max(viewportSize.height - 32, 320);

    if (fitMode === "page") {
      return Math.max(
        Math.min(availableWidth, availableHeight * pageAspect),
        240,
      );
    }
    if (fitMode === "custom") {
      return Math.max((availableWidth * zoom) / 100, 240);
    }
    return availableWidth;
  }, [fitMode, pageAspect, viewportSize.height, viewportSize.width, zoom]);

  const onDocumentLoadSuccess = ({ numPages }: PDFDocumentProxy) => {
    setLoadError(false);
    onPageCountChange(numPages);
  };

  const onPageLoadSuccess = (page: PDFPageProxy) => {
    const pageViewport = page.getViewport({ scale: 1 });
    if (pageViewport.height > 0) {
      setPageAspect(pageViewport.width / pageViewport.height);
    }
  };

  const onLoadError = () => {
    setLoadError(true);
    onPageCountChange(0);
  };

  return (
    <div
      ref={viewportRef}
      className="pdf-page-preview"
      aria-label={`PDF page ${pageNumber}`}
    >
      {loadError ? (
        <div className="pdf-preview-message" role="alert">
          <AlertTriangle aria-hidden="true" size={24} />
          <strong>Preview unavailable</strong>
          <span>
            The extracted result can still be reviewed if parsing succeeds.
          </span>
        </div>
      ) : (
        <Document
          className="pdf-document"
          file={file}
          loading={
            <div className="pdf-preview-message" role="status">
              <Loader2 className="spin" aria-hidden="true" size={24} />
              <strong>Loading PDF preview</strong>
            </div>
          }
          error={null}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={onLoadError}
          onSourceError={onLoadError}
        >
          <Page
            key={pageNumber}
            className="pdf-page"
            pageNumber={pageNumber}
            width={renderedWidth}
            loading={
              <div className="pdf-preview-message" role="status">
                <Loader2 className="spin" aria-hidden="true" size={22} />
                <strong>Rendering page {pageNumber}</strong>
              </div>
            }
            error={
              <div className="pdf-preview-message" role="alert">
                <AlertTriangle aria-hidden="true" size={22} />
                <strong>Page {pageNumber} could not be rendered</strong>
              </div>
            }
            renderAnnotationLayer={false}
            renderTextLayer
            onLoadSuccess={onPageLoadSuccess}
          />
        </Document>
      )}
    </div>
  );
}
