import os
import sys
import os
import sys

def convert_markdown_to_pdf_simple(markdown_text: str, output_path: str):
    """
    Convert markdown text to PDF using Markdown-it and WeasyPrint.

    Args:
        markdown_text (str): The markdown text to convert.
        output_path (str): The path to save the PDF file.
    """

    
    
    from markdown_pdf import MarkdownPdf
    from markdown_pdf import Section

    pdf = MarkdownPdf(toc_level=2)
    pdf.add_section(Section(markdown_text, paper_size="A4-L"))
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
    
    
import os
import sys
import tempfile
import subprocess

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

def convert_markdown_to_pdf(markdown_text: str, output_path: str, debug=False):
    """
    Convert markdown text to PDF using Pandoc (wrapper for backward compatibility).
    
    Args:
        markdown_text (str): The markdown text to convert.
        output_path (str): The path to save the PDF file.
        debug (bool): If True, keep temporary files and print verbose output.
    """
    return convert_markdown_to_pdf_simple(markdown_text, output_path)

    

    
    
if __name__ == "__main__":
    markdown_text = """
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
The formula for the area of a circle is $A = \pi r^2$.

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
    output_path = "test_output.pdf"
    convert_markdown_to_pdf(markdown_text, output_path, debug=True)
