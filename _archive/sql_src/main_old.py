from config import DRAWINGS_DIR, ensure_directories
from file_scan import list_input_files, scan_file


def main():
    ensure_directories()
    files = list_input_files()

    if not files:
        print(f"No PDF files found in {DRAWINGS_DIR}")
        return

    print(f"Found {len(files)} PDF file(s) in {DRAWINGS_DIR}\n")

    for pdf_path in files:
        print(f"Scanning: {pdf_path.name}")
        summary, output_paths = scan_file(pdf_path)

        print(f"Page count: {summary['page_count']}")
        print("Detected labels:", ", ".join(summary["detected_labels"]) or "None")
        print("Part numbers:", ", ".join(summary["pattern_summary"]["part_numbers"]) or "None")
        print("Dates:", ", ".join(summary["pattern_summary"]["dates"]) or "None")
        print("Output files:")

        for p in output_paths:
            print(f"  - {p}")

        print("\nPage text preview:\n")

        for page in summary["pages"]:
            preview = (page["pdfplumber_text"] or "[NO TEXT EXTRACTED]").replace("\n", " ")
            print(f"Page {page['page_number']}: {preview[:500]}\n")


if __name__ == "__main__":
    main()