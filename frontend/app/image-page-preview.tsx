"use client";

import { AlertTriangle, FileImage, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { BrowserPreviewKind } from "@/lib/document-api";
import type { PdfFitMode } from "./pdf-page-preview";

interface ImagePagePreviewProps {
  file: File;
  fileUrl: string;
  pageNumber: number;
  pageCount: number;
  previewKind: Exclude<BrowserPreviewKind, "pdf">;
  zoom: number;
  fitMode: PdfFitMode;
}

interface ViewportSize {
  width: number;
  height: number;
}

export function ImagePagePreview({
  file,
  fileUrl,
  pageNumber,
  pageCount,
  previewKind,
  zoom,
  fitMode,
}: ImagePagePreviewProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [viewportSize, setViewportSize] = useState<ViewportSize>({
    width: 0,
    height: 0,
  });
  const [imageAspect, setImageAspect] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
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
    const availableWidth = Math.max(viewportSize.width - 32, 240);
    const availableHeight = Math.max(viewportSize.height - 32, 280);

    if (fitMode === "page") {
      return Math.max(
        Math.min(availableWidth, availableHeight * imageAspect),
        200,
      );
    }
    if (fitMode === "custom") {
      return Math.max((availableWidth * zoom) / 100, 200);
    }
    return availableWidth;
  }, [fitMode, imageAspect, viewportSize.height, viewportSize.width, zoom]);

  if (previewKind === "tiff") {
    return (
      <div
        ref={viewportRef}
        className="image-page-preview"
        aria-label={`TIFF frame ${pageNumber}`}
      >
        <div className="pdf-preview-message tiff-preview-message" role="status">
          <FileImage aria-hidden="true" size={28} />
          <strong>TIFF preview is unavailable in this browser</strong>
          <span>
            {pageCount > 0
              ? `Frame ${pageNumber} of ${pageCount} is selected. Its parsed content is available in Results.`
              : "Parse the document to detect its frames and review their extracted content."}
          </span>
          <span>The original TIFF can still be opened from the toolbar.</span>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={viewportRef}
      className="image-page-preview"
      aria-label={`Image page ${pageNumber}`}
    >
      {isLoading && !loadError ? (
        <div className="pdf-preview-message image-loading-message" role="status">
          <Loader2 className="spin" aria-hidden="true" size={24} />
          <strong>Loading image preview</strong>
        </div>
      ) : null}
      {loadError ? (
        <div className="pdf-preview-message" role="alert">
          <AlertTriangle aria-hidden="true" size={24} />
          <strong>Preview unavailable</strong>
          <span>
            The original image can still be parsed and its extracted result
            reviewed.
          </span>
        </div>
      ) : (
        // The original object URL must be displayed without optimization or
        // network rewriting.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          className={`image-preview ${isLoading ? "is-loading" : ""}`}
          src={fileUrl}
          alt={`Original document: ${file.name}`}
          width={Math.round(renderedWidth)}
          draggable={false}
          onLoad={(event) => {
            const image = event.currentTarget;
            if (image.naturalHeight > 0) {
              setImageAspect(image.naturalWidth / image.naturalHeight);
            }
            setIsLoading(false);
            setLoadError(false);
          }}
          onError={() => {
            setIsLoading(false);
            setLoadError(true);
          }}
        />
      )}
    </div>
  );
}
