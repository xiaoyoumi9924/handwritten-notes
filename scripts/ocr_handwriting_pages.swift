import AppKit
import Foundation
import ImageIO
import Vision

struct PixelBox: Codable {
    let x: Int
    let y: Int
    let width: Int
    let height: Int
}

struct OCRLine: Codable {
    let text: String
    let confidence: Float
    let box: PixelBox
}

struct OCRPage: Codable {
    let file: String
    let width: Int
    let height: Int
    let lines: [OCRLine]
}

struct OCRDataset: Codable {
    let dataset: String
    let note: String
    let pages: [OCRPage]
}

func fail(_ message: String) -> Never {
    fputs("Error: \(message)\n", stderr)
    exit(2)
}

let arguments = CommandLine.arguments
guard arguments.count == 3 else {
    fail("Usage: swift ocr_handwriting_pages.swift <source-directory> <output-json>")
}

let sourceDirectory = URL(fileURLWithPath: arguments[1], isDirectory: true)
let outputURL = URL(fileURLWithPath: arguments[2])
let fileManager = FileManager.default
let files = try fileManager.contentsOfDirectory(at: sourceDirectory, includingPropertiesForKeys: nil)
    .filter { $0.pathExtension.lowercased() == "png" }
    .sorted { $0.lastPathComponent < $1.lastPathComponent }

guard !files.isEmpty else { fail("No PNG files found in \(sourceDirectory.path)") }

var pages: [OCRPage] = []
for fileURL in files {
    guard let imageSource = CGImageSourceCreateWithURL(fileURL as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(imageSource, 0, nil) else {
        fputs("Skip unreadable image: \(fileURL.lastPathComponent)\n", stderr)
        continue
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    request.minimumTextHeight = 0.006

    do {
        try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    } catch {
        fputs("OCR failed for \(fileURL.lastPathComponent): \(error)\n", stderr)
        continue
    }

    let observations = (request.results ?? []).sorted { left, right in
        if abs(left.boundingBox.midY - right.boundingBox.midY) > 0.004 {
            return left.boundingBox.midY > right.boundingBox.midY
        }
        return left.boundingBox.minX < right.boundingBox.minX
    }

    let lines = observations.compactMap { observation -> OCRLine? in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let rect = observation.boundingBox
        let x = max(0, Int((rect.minX * CGFloat(image.width)).rounded()))
        let y = max(0, Int(((1 - rect.maxY) * CGFloat(image.height)).rounded()))
        let width = min(image.width - x, Int((rect.width * CGFloat(image.width)).rounded()))
        let height = min(image.height - y, Int((rect.height * CGFloat(image.height)).rounded()))
        return OCRLine(
            text: candidate.string,
            confidence: candidate.confidence,
            box: PixelBox(x: x, y: y, width: max(0, width), height: max(0, height))
        )
    }

    pages.append(OCRPage(file: fileURL.lastPathComponent, width: image.width, height: image.height, lines: lines))
}

let dataset = OCRDataset(
    dataset: "new_chinese_handwriting_v1",
    note: "Apple Vision OCR candidates with line boxes. Text is uncorrected and must be reviewed; watermark-covered glyphs are not reliable labels.",
    pages: pages
)
let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
do {
    let data = try encoder.encode(dataset)
    try fileManager.createDirectory(at: outputURL.deletingLastPathComponent(), withIntermediateDirectories: true)
    try data.write(to: outputURL, options: .atomic)
    print("OCR candidate lines written: \(pages.reduce(0) { $0 + $1.lines.count }) across \(pages.count) pages")
    print("Output: \(outputURL.path)")
} catch {
    fail("Could not write OCR output: \(error)")
}
