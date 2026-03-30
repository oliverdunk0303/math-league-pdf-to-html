import fitz # PyMuPDF
import click
from pathlib import Path

def add_text_widget_in_gap(
    page, problem_count, x_start, x_end, baseline_y, 
    height=12, min_width=30, tab_stop=False, debug=False,
):
    """
    Adds a fillable text field in the horizontal gap.
    
    Args:
        page: The fitz.Page object.
        x_start: The x1 coordinate of the text before the blank.
        x_end: The x0 coordinate of the text after the blank.
        baseline_y: The 'origin' y-coordinate from your JSON (e.g., 104.47).
        height: How tall the clickable text box should be.
    """
    # 1. Define the Rectangle for the widget
    # We set the bottom (y1) to the baseline + 2 to cover the underline
    # We set the top (y0) to the bottom minus our desired height
    actual_x_end = max(x_end - 2, x_start + min_width - 2)
    rect = fitz.Rect(x_start + 2, baseline_y - (height - 2), actual_x_end, baseline_y + 2)

    # 2. Create the Widget
    widget = fitz.Widget()
    widget.rect = rect
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name = f"field_{page.number}_{problem_count}_{int(x_start)}_{int(baseline_y)}"
    widget.field_value = f"{problem_count}" if debug else ""

    # Optional: Set font size to match your PDF (10.9 in your example)
    widget.text_fontsize = height - 2  # Adjust as needed to fit within the gap
    
    # 3. Add to page
    page.add_widget(widget)

    if tab_stop:
        widget = fitz.Widget()
        # A tiny 2x2 square that is invisible but "tab-able"
        widget.rect = fitz.Rect(actual_x_end, baseline_y, actual_x_end + (10 if debug else 1), baseline_y + ((height - 2) if debug else 1))
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name = f"tab_stop_{page.number}_{problem_count}_{x_start}_{baseline_y}"

        # Note: Ensure border_width is 0 so it's truly invisible
        widget.text_maxlen = 0
        widget.field_value = f"_{problem_count}_" if debug else ""

        page.add_widget(widget)

def get_line_range(line):
    bboxes = [span['bbox'] for span in line['spans']]
    x_coords = [bbox[0] for bbox in bboxes] + [bbox[2] for bbox in bboxes]
    y_coords = [bbox[1] for bbox in bboxes] + [bbox[3] for bbox in bboxes]
    return (min(x_coords), max(x_coords)), (min(y_coords), max(y_coords))

def merge_line_ranges(line_ranges):
    x_coords = [x for line_range in line_ranges for x in line_range[0]]
    y_coords = [y for line_range in line_ranges for y in line_range[1]]
    return (min(x_coords), max(x_coords)), (min(y_coords), max(y_coords))

def get_blank_lines(page, max_height, min_width=0):
    blank_lines = []
    for path in page.get_drawings():
        for item in path["items"]:
            if item[0] == "l":  # It's a horizontal line
                p1, p2 = item[1], item[2]
                if abs(p2.x - p1.x) > min_width or abs(p2.y - p1.y) < max_height:
                    blank_lines.append({"x1": p1.x, "x2": p2.x, "y": p1.y})

    return blank_lines

@click.command()
@click.argument('input_path', type=click.Path(exists=True))
@click.option('--output_path', '-o', default=None, help="The saved filename.")
@click.option('--page_numbers', '-p', default=[1, 2], multiple=True, type=int, help="The page numbers to process, starting from 0.")
@click.option('--line_gap', '-g', default=5, type=int, help="The minimum gap between lines.")
@click.option('--start_problem_count', '-s', default=1, type=int, help="The starting problem count.")
@click.option('--field_height', '-fh', default=12, type=int, help="The height of the fillable field.")
@click.option('--min_field_width', '-mfw', default=30, type=int, help="The minimum width of the fillable field.")
@click.option('--min_line_width', '-mlw', default=0, type=int, help="The minimum line width filter for blank lines.")
@click.option('--double_tab', '-dt', is_flag=True, help="Enable double tab stops.")
@click.option('--debug', '-d', is_flag=True, help="Enable debug mode. This will fill the fields with the problem count for easier visualization.")
def convert_number_sense(
    input_path, output_path, page_numbers, line_gap, start_problem_count, 
    field_height, min_field_width, min_line_width, double_tab, debug,
):
    doc = fitz.open(input_path)

    problem_count = start_problem_count
    for page_number in page_numbers:
        page = doc.load_page(page_number)

        blank_lines = get_blank_lines(page, line_gap, min_width=min_line_width)

        # "dict" provides exact coordinates and font properties
        if debug: click.echo(f"Processing page {page.number} data: {page.get_text('text')}")
        blocks = page.get_text("dict")["blocks"]
        all_lines = [l for b in blocks if "lines" in b for l in b["lines"]]
        if debug: click.echo(f"Processing page {page.number} with {len(blocks)} blocks and {len(all_lines)} lines.")
        for i in range(len(all_lines)):
            l = all_lines[i]
            if debug: click.echo(f"Checking line {i}: {[s['text'] for s in l['spans']]}")
            if "spans" not in l or l["spans"][0]["text"].strip() != f"{problem_count}.".strip():  # Check for the specific text
                continue
            click.secho(f"--------------- \nFound problem {problem_count} on page {page.number}:", fg="white", bold=True)
            x_range, y_range = get_line_range(l)
            if debug: click.echo(f"Initial bbox: x={x_range}, y={y_range}")
            texts = [s["text"] for s in l["spans"]]
            while i+1 < len(all_lines) and all_lines[i+1]['spans'][0]['text'].strip() != f"{problem_count+1}.":
                x_range_next, y_range_next = get_line_range(all_lines[i+1])
                if y_range_next[0] > y_range[1] + line_gap:  # If the next line is close to the current line, consider it part of the same problem
                    break
                x_range, y_range = merge_line_ranges([(x_range, y_range), (x_range_next, y_range_next)])
                texts.extend(s["text"] for s in all_lines[i+1]['spans'])
                i += 1
                if debug: click.echo(f"Updated bbox: x={x_range}, y={y_range}")
            if debug: click.echo(f"Problem text: {texts}")
            longest_line = None
            for line in blank_lines:
                if y_range[0] < line["y"] < y_range[1] and  x_range[0] < line["x1"] < x_range[1]:  # Check if the line is close to the baseline and to the right of the text
                    if not longest_line or abs(line["x1"] - line["x2"]) > abs(longest_line["x1"] - longest_line["x2"]):
                        longest_line = line
            if longest_line:
                add_text_widget_in_gap(page, problem_count, longest_line["x1"], longest_line["x2"], longest_line["y"], height=field_height, min_width=min_field_width, tab_stop=double_tab, debug=debug)
                click.secho(f"Added answer field: {longest_line}", fg="green", bold=True)
            else:
                click.secho(f"[ERROR] No suitable field found!!", fg="red", bold=True)
            problem_count += 1
    
    if output_path is None:
        output_path = Path(input_path).with_name(f"{Path(input_path).stem}_fillable.pdf")
    elif output_path.endswith(".pdf"):
        output_path = Path(output_path)
    else:
        output_path = Path(output_path) / f"{Path(input_path).stem}_fillable.pdf"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    
    click.secho(f"Saved filled PDF to: {output_path}", fg="cyan", bold=True)


# Usage

if __name__ == "__main__":
   convert_number_sense()