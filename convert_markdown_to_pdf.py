import os
import sys
import argparse
import tempfile
import subprocess


def convert_markdown_to_pdf_simple(
    markdown_text: str, 
    output_path: str,
    line_height: str = "0.9",
    font_size: str = "xx-small",
    padding: str = "5px",
    paper_size: str = "A4-L",
    toc_level: int = 2
):
    """
    Convert markdown text to PDF using Markdown-it and WeasyPrint.

    Args:
        markdown_text (str): The markdown text to convert.
        output_path (str): The path to save the PDF file.
        line_height (str): CSS line-height value for body. Default "0.9".
        font_size (str): CSS font-size value for body. Default "xx-small".
        padding (str): CSS padding value for body. Default "5px".
        paper_size (str): Paper size for PDF. Default "A4-L" (A4 Landscape).
        toc_level (int): Table of contents depth level. Default 2.
    """
    from markdown_pdf import MarkdownPdf
    from markdown_pdf import Section

    # Build custom CSS for body styling
    custom_css = f"""
body {{
    line-height: {line_height};
    font-size: {font_size};
    padding: {padding};
}}

/* GitHub-flavored markdown table styling */
table {{
    border-collapse: collapse;
    margin: 1em 0;
}}

th, td {{
    border: 1px solid #d0d7de;
    padding: 6px 13px;
}}

th {{
    font-weight: 600;
    background-color: #f6f8fa;
}}
"""
    
    pdf = MarkdownPdf(toc_level=toc_level)
    pdf.add_section(Section(markdown_text, paper_size=paper_size), user_css=custom_css)
    if os.path.exists(output_path):
        os.remove(output_path)
    pdf.save(output_path)


def convert_markdown_to_pdf_old(markdown_text: str, output_path: str):
    """
    Convert markdown text to PDF using Markdown-it and WeasyPrint.

    Args:
        markdown_text (str): The markdown text to convert.
        output_path (str): The path to save the PDF file.
    """
    
    from markdown_pdf import MarkdownPdf
    from markdown_it import MarkdownIt
    from markdown_pdf import Section
    from mdit_py_plugins.texmath import texmath_plugin
    from mdit_py_plugins.dollarmath import dollarmath_plugin

    

    pdf = MarkdownPdf(toc_level=2)
    pdf.m_d = (MarkdownIt("gfm-like").enable('table').use(texmath_plugin, delimiters="brackets").use(texmath_plugin, delimiters="dollars").use(dollarmath_plugin))
    
    # Add custom CSS to improve code block rendering
    
    
    pdf.add_section(Section(markdown_text, paper_size="A4-L"))
    pdf.save(output_path)
    

def convert_markdown_to_pdf_pandoc(markdown_text: str, output_path: str, debug=False):
    """
    Convert markdown text to PDF using Pandoc command line tool.
    
    This function provides better rendering of code blocks in the PDF output.
    
    Args:
        markdown_text (str): The markdown text to convert.
        output_path (str): The path to save the PDF file.
        debug (bool): If True, keep temporary files and print verbose output.
    """
    # Create a temporary file to store the markdown content
    temp_file_path = None
    style_file_path = None
    
    try:
        # Clean the markdown text to remove problematic characters
        # Replace any control characters that might cause issues
        import re
        cleaned_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', markdown_text)
        
        # Fix code block syntax - ensure proper formatting
        # Replace triple backticks with proper markdown code block syntax
        cleaned_text = re.sub(r'```(\w*)\n', r'```\1\n', cleaned_text)
        
        
        # Create temp markdown file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as temp_file:
            temp_file_path = temp_file.name
            temp_file.write(markdown_text)
        
        if debug:
            print(f"Created temporary markdown file: {temp_file_path}")
        
        # Create temp style file
        style_file_path = create_code_style_file(debug)
        
        # Define Pandoc options for better code block rendering
        pandoc_options = [
            "pandoc",
            temp_file_path,
            "-o", output_path,
            "--pdf-engine=xelatex",  # Use xelatex for better Unicode support
            "--highlight-style=tango",  # Syntax highlighting style
            "-V", "geometry:margin=1in",  # Set margins
            "-V", "fontsize=11pt",  # Set font size
            "--standalone",
            "--toc",  # Include table of contents
            "--toc-depth=2",  # TOC depth level
            # Add custom LaTeX for code blocks
            "--include-in-header=" + style_file_path
        ]
        
        
        
        if debug:
            print(f"Running Pandoc command: {' '.join(pandoc_options)}")
        
        # Execute Pandoc command
        result = subprocess.run(
            pandoc_options,
            check=False,  # Don't raise exception on non-zero exit
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Check for errors
        if result.returncode != 0:
            print(f"Pandoc Error (exit code {result.returncode}):")
            print(f"STDERR: {result.stderr}")
            print(f"STDOUT: {result.stdout}")
            return False
        
        print(f"Successfully converted markdown to PDF: {output_path}")
        return True
        
    except Exception as e:
        print(f"Error during conversion: {str(e)}")
        if debug:
            import traceback
            traceback.print_exc()
        return False
    
    finally:
        # Clean up the temporary files unless in debug mode
        if not debug:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            if style_file_path and os.path.exists(style_file_path):
                os.unlink(style_file_path)
        else:
            print(f"Debug mode: Keeping temporary files:")
            print(f"  - Markdown file: {temp_file_path}")
            print(f"  - Style file: {style_file_path}")

def create_code_style_file(debug=False):
    """
    Create a temporary file with LaTeX styling for code blocks.
    
    Args:
        debug (bool): If True, print debug information.
        
    Returns:
        str: Path to the temporary style file.
    """
    style_content = r"""
\usepackage{fancyvrb}
\usepackage{xcolor}
\usepackage{listings}

% Define colors for syntax highlighting
\definecolor{background}{RGB}{245,245,245}
\definecolor{comment}{RGB}{0,128,0}
\definecolor{keyword}{RGB}{0,0,255}
\definecolor{string}{RGB}{163,21,21}

% Configure listings package for code blocks
\lstset{
    basicstyle=\ttfamily\small,
    backgroundcolor=\color{background},
    frame=single,
    breaklines=true,
    postbreak=\mbox{\textcolor{red}{$\hookrightarrow$}\space},
    breakatwhitespace=false,
    showspaces=false,
    showstringspaces=false,
    showtabs=false,
    tabsize=4,
    captionpos=b,
    numbers=left,
    numberstyle=\tiny\color{gray},
    numbersep=5pt,
    xleftmargin=15pt,
    framexleftmargin=15pt,
    aboveskip=10pt,
    belowskip=10pt,
    commentstyle=\color{comment},
    keywordstyle=\color{keyword}\bfseries,
    stringstyle=\color{string},
    keepspaces=true,
    columns=flexible
}

% Ensure code blocks don't get split across pages unless absolutely necessary
\BeforeBeginEnvironment{lstlisting}{\begin{minipage}{\linewidth}}
\AfterEndEnvironment{lstlisting}{\end{minipage}}
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False) as style_file:
        style_file_path = style_file.name
        style_file.write(style_content)
    
    if debug:
        print(f"Created temporary style file: {style_file_path}")
    
    return style_file_path

def convert_markdown_to_pdf(
    markdown_text: str, 
    output_path: str, 
    debug: bool = False,
    line_height: str = "0.9",
    font_size: str = "xx-small",
    padding: str = "5px",
    paper_size: str = "A4-L",
    toc_level: int = 2
):
    """
    Convert markdown text to PDF using Markdown-it and WeasyPrint (wrapper for backward compatibility).
    
    Args:
        markdown_text (str): The markdown text to convert.
        output_path (str): The path to save the PDF file.
        debug (bool): If True, keep temporary files and print verbose output.
        line_height (str): CSS line-height value for body. Default "0.9".
        font_size (str): CSS font-size value for body. Default "xx-small".
        padding (str): CSS padding value for body. Default "5px".
        paper_size (str): Paper size for PDF. Default "A4-L" (A4 Landscape).
        toc_level (int): Table of contents depth level. Default 2.
    """
    return convert_markdown_to_pdf_simple(
        markdown_text, 
        output_path,
        line_height=line_height,
        font_size=font_size,
        padding=padding,
        paper_size=paper_size,
        toc_level=toc_level
    )

    

    
    
def create_argument_parser() -> argparse.ArgumentParser:
    """
    Create and configure the argument parser for the markdown to PDF converter.
    
    Returns:
        argparse.ArgumentParser: Configured argument parser with all CLI options.
    """
    parser = argparse.ArgumentParser(
        description="Convert Markdown files to PDF with customizable styling.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.md                          # Convert input.md to input.pdf
  %(prog)s input.md -o output.pdf            # Convert to specified output file
  %(prog)s input.md --font-size small        # Use 'small' font size
  %(prog)s input.md --line-height 1.2        # Use 1.2 line height
  %(prog)s input.md --paper-size A4          # Use A4 portrait instead of landscape
        """
    )
    
    # Positional argument for input file
    parser.add_argument(
        "input",
        nargs="?",
        help="Input markdown file path. If not provided, runs demo mode."
    )
    
    # Output file argument
    parser.add_argument(
        "-o", "--output",
        dest="output",
        help="Output PDF file path. Default: input filename with .pdf extension."
    )
    
    # Styling arguments
    parser.add_argument(
        "--line-height",
        dest="line_height",
        default="0.9",
        help="CSS line-height value for body. Default: 0.9"
    )
    
    parser.add_argument(
        "--font-size",
        dest="font_size",
        default="xx-small",
        help="CSS font-size value for body. Default: xx-small"
    )
    
    parser.add_argument(
        "--padding",
        dest="padding",
        default="5px",
        help="CSS padding value for body. Default: 5px"
    )
    
    # PDF options
    parser.add_argument(
        "--paper-size",
        dest="paper_size",
        default="A4-L",
        choices=["A4", "A4-L", "A3", "A3-L", "A5", "A5-L", "Letter", "Letter-L", "Legal", "Legal-L"],
        help="Paper size for PDF. Use -L suffix for landscape. Default: A4-L"
    )
    
    parser.add_argument(
        "--toc-level",
        dest="toc_level",
        type=int,
        default=2,
        choices=[0, 1, 2, 3, 4, 5, 6],
        help="Table of contents depth level (0 to disable). Default: 2"
    )
    
    # Debug mode
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="Enable debug mode with verbose output."
    )
    
    # Demo mode
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run demo mode with sample markdown content."
    )
    
    return parser


def get_demo_markdown() -> str:
    """
    Return sample markdown content for demo/testing purposes.
    
    Returns:
        str: Sample markdown text with various formatting examples.
    """
    return """
# Markdown Test Document

## Text Formatting

This is **bold text** and this is *italic text*. You can also use ***bold and italic*** together.

## Headers

### Level 3 Header
#### Level 4 Header
##### Level 5 Header

## Lists

### Unordered List
- Item 1
- Item 2
  - Nested item 2.1
  - Nested item 2.2
- Item 3

### Ordered List
1. First item
2. Second item
3. Third item

## Tables

| Name | Age | Occupation |
|------|-----|------------|
| John | 30  | Developer  |
| Jane | 25  | Designer   |
| Bob  | 40  | Manager    |

## Math Expressions

### Inline Math
The formula for the area of a circle is $A = \\pi r^2$.

### Block Math
$$
\\begin{aligned}
E &= mc^2 \\\\
F &= ma \\\\
\\sum_{i=1}^{n} i &= \\frac{n(n+1)}{2}
\\end{aligned}
$$

### Bracket Math
\\[
\\int_{a}^{b} f(x) dx = F(b) - F(a)
\\]

### Dollar Math
$$ 
\\lim_{x \\to \\infty} \\frac{1}{x} = 0
$$

Inline math: $x^2 + y^2 = z^2$

## Code Blocks

### Inline Code
This is an example of `inline code`.

### Code Block

    # This is a code block using indentation
    def hello_world():
        print("Hello, world!")
        return None

"""


def main():
    """
    Main entry point for the markdown to PDF converter CLI.
    
    Parses command line arguments and converts the specified markdown file to PDF.
    Supports demo mode for testing without an input file.
    """
    parser = create_argument_parser()
    args = parser.parse_args()
    
    # Determine if we're in demo mode
    if args.demo or args.input is None:
        if args.input is None and not args.demo:
            print("No input file provided. Running in demo mode.")
            print("Use --help for usage information.\n")
        
        markdown_text = get_demo_markdown()
        output_path = args.output if args.output else "test_output.pdf"
        
        if args.debug:
            print(f"Demo mode: Converting sample markdown to {output_path}")
    else:
        # Read input file
        input_path = args.input
        
        if not os.path.exists(input_path):
            print(f"Error: Input file '{input_path}' not found.")
            sys.exit(1)
        
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                markdown_text = f.read()
        except Exception as e:
            print(f"Error reading input file: {e}")
            sys.exit(1)
        
        # Determine output path
        if args.output:
            output_path = args.output
        else:
            # Replace .md extension with .pdf, or append .pdf if no .md extension
            base, ext = os.path.splitext(input_path)
            output_path = base + ".pdf"
        
        if args.debug:
            print(f"Converting: {input_path} -> {output_path}")
    
    # Print styling info in debug mode
    if args.debug:
        print(f"Styling: line-height={args.line_height}, font-size={args.font_size}, padding={args.padding}")
        print(f"Paper size: {args.paper_size}, TOC level: {args.toc_level}")
    
    # Perform conversion
    try:
        convert_markdown_to_pdf(
            markdown_text=markdown_text,
            output_path=output_path,
            debug=args.debug,
            line_height=args.line_height,
            font_size=args.font_size,
            padding=args.padding,
            paper_size=args.paper_size,
            toc_level=args.toc_level
        )
        print(f"Successfully created: {output_path}")
    except Exception as e:
        print(f"Error during conversion: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
