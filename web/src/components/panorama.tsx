"use client";

import "@photo-sphere-viewer/core/index.css";
import "@photo-sphere-viewer/markers-plugin/index.css";

import { Viewer, type PanoData } from "@photo-sphere-viewer/core";
import { MarkersPlugin, type MarkerConfig } from "@photo-sphere-viewer/markers-plugin";
import { useEffect, useEffectEvent, useRef, useState } from "react";

import { fetchPicture, toSpherical, type Picture } from "@/lib/panoramax";

// orange like the boxes of the Streamlit 360° view
const BOX_STROKE = "rgb(255, 140, 0)";
const FOCUS_ZOOM = 50;

/** A flat picture covers fov degrees of a sphere: tell the viewer where it sits. */
function flatPanoData(fovDeg: number) {
  return (image: HTMLImageElement): PanoData => {
    const fullWidth = Math.round((image.width * 360) / fovDeg);
    const fullHeight = Math.round(fullWidth / 2);
    return {
      fullWidth,
      fullHeight,
      croppedWidth: image.width,
      croppedHeight: image.height,
      croppedX: Math.round((fullWidth - image.width) / 2),
      croppedY: Math.round((fullHeight - image.height) / 2),
    };
  };
}

function markersOf(
  picture: Picture,
  labels: Record<string, string>,
  focus?: string,
): MarkerConfig[] {
  const { size } = picture;
  if (!size) return []; // no frame for the annotation pixels
  return picture.annotations.map((a) => {
    const focused = a.id === focus;
    return {
      id: a.id,
      polygon: a.ring.map((p) => toSpherical(p, size, picture.fov)),
      tooltip: labels[a.id] ?? "?",
      svgStyle: {
        fill: focused ? "rgba(255, 140, 0, 0.25)" : "rgba(255, 140, 0, 0.08)",
        stroke: BOX_STROKE,
        strokeWidth: focused ? "4px" : "2px",
      },
    };
  });
}

/** Center of an annotation, as a viewer position. */
function positionOf(picture: Picture, annotationId?: string) {
  const a = picture.annotations.find((x) => x.id === annotationId);
  if (!a || !picture.size) return null;
  const xs = a.ring.map(([x]) => x);
  const ys = a.ring.map(([, y]) => y);
  const center: [number, number] = [
    (Math.min(...xs) + Math.max(...xs)) / 2,
    (Math.min(...ys) + Math.max(...ys)) / 2,
  ];
  const [yaw, pitch] = toSpherical(center, picture.size, picture.fov);
  return { yaw, pitch };
}

interface PanoramaProps {
  pictureId: string;
  /** annotation id -> text of its box: "#3 Stop · 12 m", see boxLabel */
  labels: Record<string, string>;
  /** annotation to look at */
  focus?: string;
  onFocus: (annotationId: string) => void;
  /** compass bearing of the view, null when the picture has no azimuth */
  onBearing: (bearing: number | null) => void;
}

/** 360° view of one picture, its detections boxed. Remount it (key) to change picture. */
export function Panorama({ pictureId, labels, focus, onFocus, onBearing }: PanoramaProps) {
  const container = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const [picture, setPicture] = useState<Picture | null>(null);
  const [quality, setQuality] = useState<"sd" | "loading-hd" | "hd">("sd");
  const [error, setError] = useState<string | null>(null);

  const reportBearing = useEffectEvent((yaw: number, azimuth: number | null) => {
    onBearing(azimuth === null ? null : (azimuth + (yaw * 180) / Math.PI + 360) % 360);
  });
  const selectMarker = useEffectEvent((id: string) => onFocus(id));

  useEffect(() => {
    if (!container.current) return;
    const viewer = new Viewer({
      container: container.current,
      navbar: ["zoom", "move", "fullscreen"],
      plugins: [MarkersPlugin],
      defaultZoomLvl: 0,
    });
    viewerRef.current = viewer;
    const markers = viewer.getPlugin<MarkersPlugin>(MarkersPlugin);
    markers.addEventListener("select-marker", ({ marker }) => selectMarker(marker.id));

    const controller = new AbortController();
    fetchPicture(pictureId, controller.signal)
      .then(async (pic) => {
        await viewer.setPanorama(pic.url, {
          panoData: pic.fov < 360 ? flatPanoData(pic.fov) : undefined,
          transition: false,
        });
        if (controller.signal.aborted) return;
        // yaw 0 is the image center, which faces the camera azimuth
        viewer.addEventListener("position-updated", ({ position }) =>
          reportBearing(position.yaw, pic.azimuth),
        );
        reportBearing(viewer.getPosition().yaw, pic.azimuth);
        setPicture(pic);

        // the original picture in place of the sd one, where the view is now:
        // no position given, no loader, the sd one stays until it is ready
        if (!pic.hdUrl || pic.hdUrl === pic.url) return;
        setQuality("loading-hd");
        await viewer.setPanorama(pic.hdUrl, {
          panoData: pic.fov < 360 ? flatPanoData(pic.fov) : undefined,
          transition: false,
          showLoader: false,
        });
        if (!controller.signal.aborted) setQuality("hd");
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      controller.abort();
      viewer.destroy();
      viewerRef.current = null;
    };
  }, [pictureId]);

  // the boxes, again on the HD picture
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !picture) return;
    viewer.getPlugin<MarkersPlugin>(MarkersPlugin).setMarkers(markersOf(picture, labels, focus));
  }, [picture, labels, focus, quality]);

  // a turn toward the focused box
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !picture) return;
    const position = positionOf(picture, focus);
    if (position) void viewer.animate({ ...position, zoom: FOCUS_ZOOM, speed: "8rpm" });
  }, [picture, focus]);

  return (
    <div className="absolute inset-0 bg-black">
      <div ref={container} className="h-full w-full" />
      {picture && quality !== "hd" && picture.hdUrl && (
        <span className="absolute right-4 top-4 rounded bg-black/60 px-2 py-1 text-xs text-white">
          {quality === "loading-hd" ? "Loading the HD picture…" : "SD"}
        </span>
      )}
      {error && (
        <p className="absolute inset-x-0 top-1/2 text-center text-sm text-white">
          Could not load the picture: {error}
        </p>
      )}
    </div>
  );
}
