#!/usr/bin/env swift

import AppKit
import Foundation
import Vision

guard CommandLine.arguments.count == 3 else {
    FileHandle.standardError.write(Data("用法: ocr_catalog_images.swift <图片目录> <输出 JSON>\n".utf8))
    exit(2)
}

let sourceDirectory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
let fileManager = FileManager.default
let imageURLs = try fileManager.contentsOfDirectory(
    at: sourceDirectory,
    includingPropertiesForKeys: nil,
    options: [.skipsHiddenFiles]
).filter { ["png", "jpg", "jpeg"].contains($0.pathExtension.lowercased()) }
 .sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }

var imageResults: [[String: Any]] = []

for imageURL in imageURLs {
    autoreleasepool {
        guard let image = NSImage(contentsOf: imageURL),
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let cgImage = bitmap.cgImage else {
            imageResults.append([
                "file": imageURL.lastPathComponent,
                "error": "无法读取图片",
                "observations": [],
            ])
            return
        }

        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["zh-Hans", "en-US"]
        request.usesLanguageCorrection = false

        do {
            try VNImageRequestHandler(cgImage: cgImage).perform([request])
            let observations = (request.results ?? []).sorted {
                if abs($0.boundingBox.midY - $1.boundingBox.midY) > 0.01 {
                    return $0.boundingBox.midY > $1.boundingBox.midY
                }
                return $0.boundingBox.minX < $1.boundingBox.minX
            }.compactMap { observation -> [String: Any]? in
                guard let candidate = observation.topCandidates(1).first else { return nil }
                return [
                    "text": candidate.string,
                    "confidence": Double(candidate.confidence),
                    "bbox": [
                        Double(observation.boundingBox.minX),
                        Double(observation.boundingBox.minY),
                        Double(observation.boundingBox.width),
                        Double(observation.boundingBox.height),
                    ],
                ]
            }
            imageResults.append([
                "file": imageURL.lastPathComponent,
                "observations": observations,
            ])
        } catch {
            imageResults.append([
                "file": imageURL.lastPathComponent,
                "error": error.localizedDescription,
                "observations": [],
            ])
        }
    }
}

let formatter = ISO8601DateFormatter()
let document: [String: Any] = [
    "schema_version": 1,
    "generated_at": formatter.string(from: Date()),
    "source_directory": sourceDirectory.path,
    "image_count": imageResults.count,
    "images": imageResults,
]
let data = try JSONSerialization.data(withJSONObject: document, options: [.prettyPrinted, .sortedKeys])
try data.write(to: outputURL, options: .atomic)
print("已识别 \(imageResults.count) 张图片: \(outputURL.path)")
