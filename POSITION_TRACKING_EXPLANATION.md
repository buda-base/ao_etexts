# Position Tracking Issue in TEI to Standoff Conversion

## Summary

The `align_div_milestones_nl()` function is necessary as a post-processing step because of an architectural limitation in how the conversion pipeline processes different marker types sequentially.

## Root Cause

The conversion pipeline processes markers in this order:
1. `convert_div_boundaries()` - processes `<div_start_marker/>` and `<div_end_marker/>`
2. `convert_milestones()` - processes `<milestone_marker>ID</milestone_marker>`
3. Other conversions...

### The Problem

When `convert_div_boundaries()` runs:
- It finds div markers at their original positions in the text
- Records these positions in `annotations['div_boundaries']`
- Uses `get_string()` to remove the markers and track position shifts
- `get_string()` applies position corrections to ALL existing annotations
- **BUT**: `annotations['milestones']` doesn't exist yet!
- So milestone marker positions don't get corrected for the div marker removals

When `convert_milestones()` runs:
- The text has already been modified by `convert_div_boundaries()`
- Milestone markers are now at DIFFERENT positions than in the original text
- It records these shifted positions in `annotations['milestones']`
- Uses `get_string()` to remove milestone markers
- `get_string()` now corrects `div_boundaries` for milestone removals
- But div boundaries and milestones started from different reference points!

### Concrete Example (from new_format_milestones test)

**Original preprocessed text:**
```
Position 0:   <milestone_marker>div1_0001</milestone_marker>
Position 48:  <div_start_marker/>
Position 215: <div_end_marker/>
Position 234: <milestone_marker>div1_0002</milestone_marker>
Position 282: <div_start_marker/>
Position 430: <div_end_marker/>
```

**After convert_div_boundaries():**
- `div_boundaries[0]` = `{cstart: 48, cend: 215}` ← recorded from original
- `div_boundaries[1]` = `{cstart: 282, cend: 430}` ← recorded from original
- Text is shorter (markers removed, `\n\n` added)
- Milestone markers shifted:
  - `div1_0001` at position 0 (unchanged)
  - `div1_0002` at position ~200 (was 234, shifted by div marker removals)

**After convert_milestones():**
- `milestones['div1_0002']` = 193 ← recorded from shifted position
- `div_boundaries[0]['cend']` = 150 ← adjusted for milestone removals from position 215

**Result:** Misalignment
- Milestone `div1_0002` at 126 (after further processing)
- Div 0 ends at 120
- Div 1 starts at 128
- The milestone is neither at the div end nor at the div start!

## Why align_div_milestones_nl() is Necessary

The function performs post-processing to fix misalignment:
1. Looks at the FINAL text
2. Finds milestones between div boundaries
3. Adjusts div boundaries to align with those milestones
4. Skips trailing newlines for cleaner boundaries

## Alternative Solutions Considered

### 1. Process milestones before divs
❌ Won't work: div processing would shift milestone positions, same problem in reverse

### 2. Pre-register milestones with placeholder positions
⚠️ Could work but requires:
- Two-pass processing (find all milestone IDs first)
- More complex code
- Knowing milestone structure in advance

### 3. Process all markers in a single pass
⚠️ Would require:
- Major refactoring of the entire conversion pipeline
- Replacing the current modular design
- Higher complexity

### 4. Keep post-processing alignment (current solution)
✅ Advantages:
- Simplest solution
- No major refactoring required
- Works for both old and new milestone formats
- Already implemented and tested
- Modular and maintainable

## Conclusion

`align_div_milestones_nl()` is not "magic" - it's a necessary post-processing step that compensates for the sequential marker processing architecture. The `get_string()` function cannot track positions across marker types that are processed in separate steps because annotations are created at different stages.

The current design is optimal given the constraints:
- Maintains modularity (each marker type has its own conversion function)
- Minimizes code complexity
- Handles edge cases (newlines, text boundaries, etc.)
- Works correctly with the test-driven approach
