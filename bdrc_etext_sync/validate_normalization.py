"""
Normalization validation module.

This module validates that text content in TEI XML files follows the normalization
rules specified in doc/text_content_normalization.md, except for the NFC normalization
rule for non-Tibetan text.
"""

import re
import unicodedata
import logging
import os
from lxml import etree
from . import normalization


def _is_tibetan_char(char):
    """Check if a character is in the Tibetan Unicode block."""
    return '\u0F00' <= char <= '\u0FFF'


def _has_tibetan_chars(text):
    """Check if text contains any Tibetan characters."""
    return any(_is_tibetan_char(c) for c in text)


def _check_bom(text):
    """Check for BOM (Byte Order Mark) characters."""
    errors = []
    if '\uFEFF' in text:
        errors.append("Text contains BOM (Byte Order Mark) character")
    return errors


def _find_preserve_sections(text):
    """
    Find line ranges that are within xml:space="preserve" sections.
    Returns a set of line numbers (1-indexed) that are between a line containing
    space="preserve" and a line containing </p>.
    """
    lines = text.split('\n')
    preserve_lines = set()
    
    # Find all preserve start lines (lines containing space="preserve")
    preserve_start_lines = []
    for i, line in enumerate(lines, 1):
        if 'space="preserve"' in line or 'xml:space="preserve"' in line:
            preserve_start_lines.append(i)
    
    # For each preserve start, find the corresponding </p> line
    for start_line in preserve_start_lines:
        # Look for </p> after the preserve line
        for i in range(start_line, len(lines) + 1):
            if '</p>' in lines[i - 1]:
                # Lines between start_line (exclusive) and i (exclusive) are in preserve section
                for line_num in range(start_line + 1, i):
                    preserve_lines.add(line_num)
                break
    
    return preserve_lines


def _check_spaces_at_line_edges(text):
    """
    Check that there are no spaces at the beginning or end of lines,
    but only for lines that are strictly after a line with space="preserve"
    and strictly before a line with </p>.
    """
    errors = []
    lines = text.split('\n')
    preserve_lines = _find_preserve_sections(text)
    
    for i, line in enumerate(lines, 1):
        # Only check lines that are in preserve sections
        if i in preserve_lines:
            if line and line[0] == ' ':
                errors.append(f"Line {i} starts with a space")
            if line and line[-1] == ' ':
                errors.append(f"Line {i} ends with a space")
    return errors


def _check_empty_lines(text):
    """Check that there are no empty lines, except the last line which can be empty."""
    errors = []
    lines = text.split('\n')
    for i, line in enumerate(lines, 1):
        if line == '':
            # Allow the last line to be empty
            if i == len(lines):
                continue
            errors.append(f"Line {i} is empty")
    return errors


def _check_non_ascii_spaces(text):
    """Check that all spaces are ASCII spaces (no tabs or other Unicode spaces)."""
    errors = []
    unicode_spaces = [
        "\u00A0",  # NO-BREAK SPACE
        "\u1680", "\u2000", "\u2001", "\u2002", "\u2003", "\u2004",
        "\u2005", "\u2006", "\u2007", "\u2008", "\u2009", "\u200A",
        "\u202F", "\u205F", "\u3000",  # narrow, medium, ideographic spaces
        "\t", "\x0b", "\x0c"           # TAB, VT, FF
    ]
    
    for i, char in enumerate(text):
        if char in unicode_spaces:
            char_name = unicodedata.name(char, f"U+{ord(char):04X}")
            # Calculate line and column
            line_num = text[:i].count('\n') + 1
            col_num = i - text[:i].rfind('\n')
            errors.append(f"Line {line_num}, column {col_num}: non-ASCII space character ({char_name})")
    return errors


def _check_consecutive_spaces(text):
    """
    Check that there are no consecutive spaces, but ignore consecutive spaces
    at the beginning and end of lines (regardless of preserve sections).
    """
    errors = []
    lines = text.split('\n')
    
    for match in re.finditer(r' {2,}', text):
        start = match.start()
        line_num = text[:start].count('\n') + 1
        col_num = start - text[:start].rfind('\n')
        
        # Get the line content
        line = lines[line_num - 1]
        
        # Calculate the position within the line (0-indexed)
        line_start_pos = start - (text[:start].rfind('\n') + 1)
        match_end_pos = line_start_pos + len(match.group())
        
        # Count leading spaces in the line
        leading_spaces = len(line) - len(line.lstrip(' '))
        # Count trailing spaces in the line
        trailing_spaces = len(line) - len(line.rstrip(' '))
        
        # Skip if the consecutive spaces are at the beginning of the line
        # (the match starts within the leading spaces)
        if line_start_pos < leading_spaces:
            continue
        
        # Skip if the consecutive spaces are at the end of the line
        # (the match ends within or at the trailing spaces)
        if match_end_pos > len(line) - trailing_spaces:
            continue
        
        errors.append(f"Line {line_num}, column {col_num}: consecutive spaces found")
    return errors


def _check_tibetan_normalization(text):
    """Check that Tibetan text is normalized according to pybo rules."""
    errors = []
    
    # Split text into lines to provide better error messages
    lines = text.split('\n')
    line_starts = [0]
    for line in lines[:-1]:
        line_starts.append(line_starts[-1] + len(line) + 1)  # +1 for newline
    
    # Check each line for Tibetan characters
    for line_idx, line in enumerate(lines):
        if not _has_tibetan_chars(line):
            continue
        
        # Normalize the line according to Tibetan rules
        normalized = normalization.normalize_unicode_tib(line)
        
        # Check if normalization changed anything
        if normalized != line:
            # If lengths differ, report that
            if len(normalized) != len(line):
                errors.append(
                    f"Line {line_idx + 1}: Tibetan text structure not normalized "
                    f"(length changed from {len(line)} to {len(normalized)})"
                )
            else:
                # Find the first difference (when lengths are the same)
                for i, (orig_char, norm_char) in enumerate(zip(line, normalized)):
                    if orig_char != norm_char:
                        col_num = i + 1
                        errors.append(
                            f"Line {line_idx + 1}, column {col_num}: Tibetan text not normalized "
                            f"(expected '{norm_char}' but found '{orig_char}')"
                        )
                        break
    
    return errors


def validate_text_normalization(text):
    """
    Validate that text follows normalization rules.
    
    Args:
        text: The text string to validate
        
    Returns:
        tuple: (errors, warnings) where each is a list of error/warning messages
    """
    logger = logging.getLogger(__name__)
    errors = []
    warnings = []
    
    logger.debug("Starting text normalization validation (text length: %d characters)", len(text))
    
    # Check BOM
    logger.debug("Checking for BOM characters...")
    bom_errors = _check_bom(text)
    errors.extend(bom_errors)
    if bom_errors:
        logger.debug("Found %d BOM error(s)", len(bom_errors))
    
    # Check spaces at line edges
    logger.debug("Checking for spaces at line edges...")
    edge_errors = _check_spaces_at_line_edges(text)
    errors.extend(edge_errors)
    if edge_errors:
        logger.debug("Found %d line edge error(s)", len(edge_errors))
    
    # Check empty lines in the XML file
    logger.debug("Checking for empty lines...")
    empty_line_errors = _check_empty_lines(text)
    errors.extend(empty_line_errors)
    if empty_line_errors:
        logger.debug("Found %d empty line error(s)", len(empty_line_errors))
    
    # Check non-ASCII spaces
    logger.debug("Checking for non-ASCII spaces...")
    space_errors = _check_non_ascii_spaces(text)
    errors.extend(space_errors)
    if space_errors:
        logger.debug("Found %d non-ASCII space error(s)", len(space_errors))
    
    # Check consecutive spaces
    logger.debug("Checking for consecutive spaces...")
    consecutive_errors = _check_consecutive_spaces(text)
    errors.extend(consecutive_errors)
    if consecutive_errors:
        logger.debug("Found %d consecutive space error(s)", len(consecutive_errors))
    
    # Check Tibetan normalization
    logger.debug("Checking Tibetan text normalization...")
    tibetan_errors = _check_tibetan_normalization(text)
    errors.extend(tibetan_errors)
    if tibetan_errors:
        logger.debug("Found %d Tibetan normalization error(s)", len(tibetan_errors))
    
    logger.debug("Text normalization validation complete: %d error(s), %d warning(s)", len(errors), len(warnings))
    return errors, warnings


def validate_tei_root_normalization(filepath):
    """
    Validate normalization for a TEI XML file by reading it as text.
    
    Args:
        filepath: Path to the TEI XML file to read and validate as text
        
    Returns:
        tuple: (errors, warnings) where each is a list of error/warning messages
    """
    logger = logging.getLogger(__name__)
    logger.debug("Validating normalization for %s (reading as text)", filepath)
    
    try:
        # Read the XML file as text
        logger.debug("Reading XML file as text: %s", filepath)
        if not os.path.isfile(filepath):
            return [f"{filepath}: File not found"], []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()
        
        logger.debug("Read file: %d characters, %d lines", len(text), text.count('\n') + 1)
        
        # Validate the file text
        errors, warnings = validate_text_normalization(text)
        
        # Add file context to error messages
        file_errors = [f"{filepath}: {err}" for err in errors]
        file_warnings = [f"{filepath}: {warn}" for warn in warnings]
        
        if errors:
            logger.info("Normalization validation for %s: %d error(s) found", filepath, len(errors))
        elif warnings:
            logger.info("Normalization validation for %s: passed with %d warning(s)", filepath, len(warnings))
        else:
            logger.debug("Normalization validation for %s: passed", filepath)
        
        return file_errors, file_warnings
        
    except UnicodeDecodeError as e:
        logger.error("Error reading file %s (encoding issue): %s", filepath, str(e))
        return [f"{filepath}: Error reading file (encoding issue): {str(e)}"], []
    except Exception as e:
        logger.error("Error validating normalization for %s: %s", filepath, str(e), exc_info=True)
        return [f"{filepath}: Error processing file: {str(e)}"], []


def validate_tei_file_normalization(filepath):
    """
    Validate normalization for a TEI XML file by reading it as text.
    
    Args:
        filepath: Path to the TEI XML file
        
    Returns:
        tuple: (errors, warnings) where each is a list of error/warning messages
    """
    logger = logging.getLogger(__name__)
    logger.debug("Validating XML file as text: %s", filepath)
    
    try:
        # Read the XML file as text directly
        if not os.path.isfile(filepath):
            return [f"{filepath}: File not found"], []
        
        logger.debug("Reading XML file as text: %s", filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()
        
        logger.debug("Read file: %d characters, %d lines", len(text), text.count('\n') + 1)
        
        # Validate the file text
        errors, warnings = validate_text_normalization(text)
        
        # Add file context to error messages
        file_errors = [f"{filepath}: {err}" for err in errors]
        file_warnings = [f"{filepath}: {warn}" for warn in warnings]
        
        if errors:
            logger.info("Normalization validation for %s: %d error(s) found", filepath, len(errors))
        elif warnings:
            logger.info("Normalization validation for %s: passed with %d warning(s)", filepath, len(warnings))
        else:
            logger.debug("Normalization validation for %s: passed", filepath)
        
        return file_errors, file_warnings
        
    except UnicodeDecodeError as e:
        logger.error("Error reading file %s (encoding issue): %s", filepath, str(e))
        return [f"{filepath}: Error reading file (encoding issue): {str(e)}"], []
    except Exception as e:
        logger.error("Error validating normalization for %s: %s", filepath, str(e), exc_info=True)
        return [f"{filepath}: Error processing file: {str(e)}"], []

