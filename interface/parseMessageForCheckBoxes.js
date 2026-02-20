function parseMessageForCheckBoxes(text) {
    let result = { text: "" };
    // NOTE: Commands are only parsed from the *first line* of the message,
    // and only when they appear outside inline/fenced backtick code spans.
    let processedText = text;
    let lines = (text ?? "").split(/\r?\n/);

    /**
     * Return ranges [start, end) for inline markdown code spans delimited by backticks.
     *
     * Supports variable-length backtick fences (e.g. `code`, ``code ` inside```, ```code```).
     * If an opening backtick fence is not closed on the same line, the code span is treated
     * as running until end-of-line.
     *
     * @param {string} line
     * @returns {{start: number, end: number}[]}
     */
    const getInlineCodeRanges = (line) => {
        const ranges = [];
        if (!line) return ranges;

        let i = 0;
        let inSpan = false;
        let fenceLen = 0;
        let spanStart = -1;

        while (i < line.length) {
            // Count run length of consecutive backticks at i
            if (line[i] === "`") {
                let j = i;
                while (j < line.length && line[j] === "`") j++;
                const runLen = j - i;

                if (!inSpan) {
                    inSpan = true;
                    fenceLen = runLen;
                    spanStart = i;
                } else if (runLen === fenceLen) {
                    // Close span, include closing fence
                    ranges.push({ start: spanStart, end: j });
                    inSpan = false;
                    fenceLen = 0;
                    spanStart = -1;
                }

                i = j;
                continue;
            }
            i++;
        }

        // Unclosed opening fence: treat as code span until end-of-line
        if (inSpan && spanStart >= 0) {
            ranges.push({ start: spanStart, end: line.length });
        }

        return ranges;
    };

    /**
     * Check whether an index is within any [start, end) range.
     * @param {number} idx
     * @param {{start: number, end: number}[]} ranges
     * @returns {boolean}
     */
    const isIndexInRanges = (idx, ranges) => {
        for (const r of ranges) {
            if (idx >= r.start && idx < r.end) return true;
        }
        return false;
    };

    /**
     * Find the first regex match in the provided line that is NOT inside a backtick code span.
     * @param {string} line
     * @param {RegExp} regex
     * @returns {{match: RegExpExecArray, index: number} | null}
     */
    const findFirstMatchOutsideInlineCode = (line, regex) => {
        const ranges = getInlineCodeRanges(line);
        const flags = regex.flags.includes("g") ? regex.flags : `${regex.flags}g`;
        const re = new RegExp(regex.source, flags);

        let m;
        while ((m = re.exec(line)) !== null) {
            const idx = m.index ?? 0;
            if (!isIndexInRanges(idx, ranges)) {
                return { match: m, index: idx };
            }
            // Avoid infinite loops on zero-length matches
            if (m[0].length === 0) re.lastIndex++;
        }
        return null;
    };

    /**
     * Replace a single match occurrence at an exact index with a single space.
     * @param {string} line
     * @param {number} index
     * @param {number} length
     * @returns {string}
     */
    const replaceAtIndexWithSpace = (line, index, length) => {
        return `${line.slice(0, index)} ${line.slice(index + length)}`;
    };

    // Improved processing for removing commands and handling spaces
    const processCommand = (regex, key, isFlag = false) => {
        const firstLine = lines[0] ?? "";
        const found = findFirstMatchOutsideInlineCode(firstLine, regex);
        if (found) {
            const match = found.match;
            if (key) {
                // Assign matched number or true for flags, if isFlag is true then we don't expect a capturing group
                result[key] = isFlag ? true : match[1];
            }
            // Replace the found command with a space, and we'll trim and replace multiple spaces later
            lines[0] = replaceAtIndexWithSpace(firstLine, found.index, match[0].length);
        }
    };

    // Process each command with regex adjusted for case insensitivity and improved whitespace handling
    processCommand(/\/history\s+(\d+)/i, "enable_previous_messages");
    processCommand(/\/detailed\s+(\d+)/i, "provide_detailed_answers");
    processCommand(/\/delete\b/i, "delete_last_turn", true);
    processCommand(/\/scholar\b/i, "googleScholar", true);
    processCommand(/\/search_exact\b/i, "search_exact", true);
    processCommand(/\/search\b/i, "perform_web_search", true);
    processCommand(/\/more\b/i, "tell_me_more", true);
    processCommand(/\/ensemble\b/i, "ensemble", true);
    processCommand(/\/execute\b/i, "execute", true);
    processCommand(/\/draw\b/i, "draw", true);

    // Handle commands without numbers specifically, to ensure no leftover words like "then_no_number"
    // Only remove these bare tokens if they occur on the FIRST LINE and outside backticks.
    const removeBareTokenFromFirstLine = (regex) => {
        const firstLine = lines[0] ?? "";
        const found = findFirstMatchOutsideInlineCode(firstLine, regex);
        if (found) {
            lines[0] = replaceAtIndexWithSpace(firstLine, found.index, found.match[0].length);
        }
    };
    removeBareTokenFromFirstLine(/\/history\b/i);
    removeBareTokenFromFirstLine(/\/detailed\b/i);

    processedText = lines.join("\n");

    // Replace multiple spaces with a single space and trim leading/trailing spaces
    processedText = processedText.replace(/\s+/g, ' ').trim();

    // Update the processed text in the result
    result.text = processedText;
    // Log the result for debugging without the text field.
    console.log({ ...result, text: "" });
    return result;
}

function mergeOptions(parsed_message, options) {
    // Destructure to exclude 'text' from parsed_message and capture the rest
    const { text, ...parsedOptions } = parsed_message;

    // Merge options with parsedOptions, allowing the latter to take precedence
    const mergedOptions = { ...options, ...parsedOptions };

    return mergedOptions;
}

// Enhanced whitespace normalization
function normalizeWhitespace(str) {
    return str.replace(/\s+/g, " ").trim(); // Replace various whitespace with single spaces
}


// Helper function for assertions (updated)
function assertObjectEquals(obj1, obj2, testDescription) {
  const keys1 = Object.keys(obj1);
  const keys2 = Object.keys(obj2);

  console.assert(keys1.length === keys2.length, `${testDescription} - Objects have different keys`);

  for (const key of keys1) {
    console.assert(obj1[key] === obj2[key], `${testDescription} - Values for key '${key}' do not match obj1: '${obj1[key]}' obj2: '${obj2[key]}'`);
  }
}

// Test function with detailed descriptions
function testParseMessageForCheckBoxes() {
    // Test Cases - Basic Functionality
    const input1 = "Hello world /history 3";
    const expectedOutput1 = { text: "Hello world", enable_previous_messages: "3" };
    const result1 = parseMessageForCheckBoxes(input1);
    assertObjectEquals(result1, expectedOutput1, "Test Case 1 - Basic Functionality (History)");

    const input2 = "/scholar Some interesting topic /search";
    const expectedOutput2 = { text: "Some interesting topic", googleScholar: true, perform_web_search: true };
    const result2 = parseMessageForCheckBoxes(input2);
    assertObjectEquals(result2, expectedOutput2, "Test Case 2 - Basic Functionality (Scholar & Search)");

    const input3 = "Let's discuss this /history then_no_number";
    const expectedOutput3 = { text: "Let's discuss this then_no_number" }; // We did not remove then_no_number since it could be relevant part of text itself.
    const result3 = parseMessageForCheckBoxes(input3);
    assertObjectEquals(result3, expectedOutput3, "Test Case 3 - Error Handling (Invalid History)");

    // Test Cases - Edge Cases and Variations
    const input4 = "/search /scholar What is the meaning of life?";
    const expectedOutput4 = { text: "What is the meaning of life?", googleScholar: true, perform_web_search: true };
    const result4 = parseMessageForCheckBoxes(input4);
    assertObjectEquals(result4, expectedOutput4, "Test Case 4 - Command Order Variation");

    const input5 = "  /history  2     /scholar";
    const expectedOutput5 = { text: "", googleScholar: true, enable_previous_messages: "2" };
    const result5 = parseMessageForCheckBoxes(input5);
    assertObjectEquals(result5, expectedOutput5, "Test Case 5 - Whitespace Handling");

    const input6 = "/HiStOrY 5 /ScHoLaR"; 
    const expectedOutput6 = { text: "", googleScholar: true, enable_previous_messages: "5" };
    const result6 = parseMessageForCheckBoxes(input6);
    assertObjectEquals(result6, expectedOutput6, "Test Case 6 - Case Insensitivity"); 

    const input7 = "This is not a command /historyish";
    const expectedOutput7 = { text: "This is not a command /historyish" };
    const result7 = parseMessageForCheckBoxes(input7);
    assertObjectEquals(result7, expectedOutput7, "Test Case 7 - Text with Invalid Command");

    console.log("All tests passed!"); 
}

// Call the test function
// testParseMessageForCheckBoxes(); 


function testParseMessageForCheckBoxesV2() {
    // Test scenarios
    const testCases = [
        { input: "/history 3", expected: { text: "", enable_previous_messages: "3" } },
        { input: "SomeOtherMessageContent /history 2 messageContent", expected: { text: "SomeOtherMessageContent messageContent", enable_previous_messages: "2" } },
        { input: "/scholar Some text here", expected: { text: "Some text here", googleScholar: true } },
        { input: "Text before /search text after", expected: { text: "Text before text after", perform_web_search: true } },
        { input: "/history", expected: { text: "" } }, // Command without number
        { input: "No commands here", expected: { text: "No commands here" } }, // No commands
        { input: "/history 5 /scholar /search", expected: { text: "", enable_previous_messages: "5", googleScholar: true, perform_web_search: true } }, // Multiple commands
        { input: "/history5", expected: { text: "/history5" } }, // Invalid command format
        { input: "/history then_no_number", expected: { text: "then_no_number" } }, // Invalid history command, we keep then_no_number as part of text
        { input: "/detailed 2 /history 3", expected: { text: "", provide_detailed_answers: "2", enable_previous_messages: "3" } }, // Both detailed and history commands

        // New behavior: commands only on FIRST LINE, and not inside backticks
        { input: "Line1\n/search", expected: { text: "Line1 /search" } }, // /search on line 2 => ignored
        { input: "Use `/search` please", expected: { text: "Use `/search` please" } }, // inside inline code => ignored
        { input: "```/search``` now", expected: { text: "```/search``` now" } } // fenced on same line => ignored
    ];

    // Execute each test case
    testCases.forEach((testCase, index) => {
        const result = parseMessageForCheckBoxes(testCase.input);
        console.log(`Test Case ${index + 1}:`, result);

        // Assert for expected keys and text
        Object.entries(testCase.expected).forEach(([key, value]) => {
            console.assert(result[key] === value, `Failed on ${key} with input "${testCase.input}". Expected: ${value}, Got: ${result[key]}`);
        });

        // Assert for no unexpected keys in the result
        Object.keys(result).forEach((key) => {
            console.assert(testCase.expected.hasOwnProperty(key), `Unexpected key "${key}" in result for input "${testCase.input}".`);
        });
    });

    console.log("Testing completed.");
}

// Invoke the testing function
// testParseMessageForCheckBoxesV2();

function comprehensiveTestParseMessageForCheckBoxes() {
    const testCases = [
        { input: "Hello world /history 3", expected: { text: "Hello world", enable_previous_messages: "3" } },
        { input: "/scholar Some interesting topic /search", expected: { text: "Some interesting topic", googleScholar: true, perform_web_search: true } },
        { input: "Let's discuss this /history then_no_number", expected: { text: "Let's discuss this then_no_number" } },
        { input: "/search /scholar What is the meaning of life?", expected: { text: "What is the meaning of life?", googleScholar: true, perform_web_search: true } },
        { input: "  /history  2     /scholar", expected: { text: "", googleScholar: true, enable_previous_messages: "2" } },
        { input: "/HiStOrY 5 /ScHoLaR", expected: { text: "", googleScholar: true, enable_previous_messages: "5" } },
        { input: "This is not a command /historyish", expected: { text: "This is not a command /historyish" } },
        { input: "/search What's the weather like? /scholar", expected: { text: "What's the weather like?", googleScholar: true, perform_web_search: true } },
        { input: "/history3/scholar", expected: { text: "/history3/scholar" } },
        { input: "/ history 2", expected: { text: "/ history 2" } },
        { input: "This is a history lesson", expected: { text: "This is a history lesson" } },
        { input: "/history two", expected: { text: "two" } },
        { input: "Pre /HiStOrY 4 post", expected: { text: "Pre post", enable_previous_messages: "4" } },

        // New behavior: commands only on FIRST LINE, and not inside backticks
        { input: "First line ok /search\nSecond line /scholar", expected: { text: "First line ok Second line /scholar", perform_web_search: true } },
        { input: "Use `/history 3` literally", expected: { text: "Use `/history 3` literally" } }
    ];

    testCases.forEach((testCase, index) => {
        const result = parseMessageForCheckBoxes(testCase.input);
        console.log(`Comprehensive Test Case ${index + 1}:`, result);

        Object.entries(testCase.expected).forEach(([key, value]) => {
            console.assert(result[key] === value, `Failed on ${key} with input "${testCase.input}". Expected: ${value}, Got: ${result[key]}`);
        });

        Object.keys(result).forEach((key) => {
            console.assert(testCase.expected.hasOwnProperty(key), `Unexpected key "${key}" in result for input "${testCase.input}".`);
        });
    });

    console.log("Comprehensive testing completed.");
}

// comprehensiveTestParseMessageForCheckBoxes();


function comprehensiveTestParseMessageForCheckBoxesV2() {
    const testCases = [
        { input: "/history 3", expected: { text: "", enable_previous_messages: "3" } },
        { input: "SomeOtherMessageContent /history 2 messageContent", expected: { text: "SomeOtherMessageContent messageContent", enable_previous_messages: "2" } },
        { input: "/scholar Some text here", expected: { text: "Some text here", googleScholar: true } },
        { input: "Text before /search text after", expected: { text: "Text before text after", perform_web_search: true } },
        { input: "/history", expected: { text: "" } },
        { input: "No commands here", expected: { text: "No commands here" } },
        { input: "/history 5 /scholar /search", expected: { text: "", enable_previous_messages: "5", googleScholar: true, perform_web_search: true } },
        { input: "/history5", expected: { text: "/history5" } },
        { input: "/history then_no_number", expected: { text: "then_no_number" } },
        { input: "/detailed 2 /history 3", expected: { text: "", provide_detailed_answers: "2", enable_previous_messages: "3" } },
        { input: "/search What's the weather like? /scholar", expected: { text: "What's the weather like?", googleScholar: true, perform_web_search: true } },
        { input: "/history3/scholar", expected: { text: "/history3/scholar" } },
        { input: "/ history 2", expected: { text: "/ history 2" } },
        { input: "This is a history lesson", expected: { text: "This is a history lesson" } },
        { input: "/history two", expected: { text: "two" } },
        { input: "Pre /HiStOrY 4 post", expected: { text: "Pre post", enable_previous_messages: "4" } }
    ];

    testCases.forEach((testCase, index) => {
        const result = parseMessageForCheckBoxes(testCase.input);
        console.log(`Comprehensive Test Case ${index + 1}:`, result);

        Object.entries(testCase.expected).forEach(([key, value]) => {
            console.assert(result[key] === value, `Test Case ${index + 1} failed for key "${key}". Expected "${value}", found "${result[key]}"`);
        });

        Object.keys(result).forEach((key) => {
            console.assert(key === 'text' || testCase.expected.hasOwnProperty(key), `Test Case ${index + 1} unexpected key "${key}" found.`);
        });
    });

    console.log("Comprehensive testing completed.");
}

// comprehensiveTestParseMessageForCheckBoxesV2();


// ===========================================================================
// @memory Reference Parsing (Deliberate Memory Attachment)
// ===========================================================================

/**
 * Parse @memory references from message text.
 * 
 * Supports the following formats:
 * - @memory:claim_id (e.g., @memory:abc123)
 * - @mem:claim_id (shorter syntax)
 * - @friendly_id (e.g., @prefer_morning_workouts_a3f2 for claims)
 * - @context_id (e.g., @ssdva or @work_context_a3b2 for contexts)
 * 
 * Friendly IDs for both claims and contexts are captured. The backend's
 * resolve_reference() will determine whether each ID refers to a claim
 * or a context (tries claim first, then context, then context name).
 * 
 * Returns the claim IDs found and the cleaned text with references removed.
 * 
 * @param {string} text - The message text to parse
 * @returns {{cleanText: string, claimIds: string[], friendlyIds: string[]}} - Object with cleaned text, legacy claim IDs, and friendly IDs
 */
function parseMemoryReferences(text) {
    if (!text) {
        return { cleanText: '', claimIds: [], friendlyIds: [] };
    }
    
    var claimIds = [];
    var friendlyIds = [];
    
    // 1. Legacy regex: @memory:claim_id or @mem:claim_id (UUID format)
    var legacyRegex = /@(?:memory|mem):([a-zA-Z0-9-]+)/g;
    var match;
    
    // Collect legacy @memory: positions so we can skip them in step 2
    var legacyPositions = [];
    while ((match = legacyRegex.exec(text)) !== null) {
        var claimId = match[1];
        if (claimId && claimIds.indexOf(claimId) === -1) {
            claimIds.push(claimId);
        }
        legacyPositions.push({ start: match.index, end: match.index + match[0].length });
    }
    
    // 2. Friendly_id regex: @identifier (alphanumeric + underscores + hyphens, 3+ chars total)
    // Matches both claim friendly_ids (e.g., @prefer_morning_a3f2) and context friendly_ids
    // (e.g., @ssdva, @work_context_a3b2). Minimum 3 chars to reduce false positives.
    //
    // Rules:
    // - Must start with a letter
    // - 3+ total characters (letter + 2 or more alphanumeric/underscore/hyphen chars)
    // - Must be preceded by start-of-string or whitespace (not part of an email like user@domain)
    // - Must NOT be the legacy @memory: or @mem: prefix
    //
    // We use a global regex that matches any @word pattern, then manually check the
    // preceding character to ensure it's at the start of the string or after whitespace.
    // This avoids lookbehind assertions which are not supported in all browsers.
    var friendlyRegex = /@([a-zA-Z][a-zA-Z0-9_-]{2,})/g;
    
    while ((match = friendlyRegex.exec(text)) !== null) {
        var fid = match[1];
        var matchStart = match.index;
        
        // Check that @ is at start of string or preceded by whitespace (not part of email)
        if (matchStart > 0 && !/\s/.test(text.charAt(matchStart - 1))) {
            continue;
        }
        
        // Skip if this position overlaps with a legacy @memory:/@mem: match
        var isLegacy = false;
        for (var i = 0; i < legacyPositions.length; i++) {
            if (matchStart >= legacyPositions[i].start && matchStart < legacyPositions[i].end) {
                isLegacy = true;
                break;
            }
        }
        if (isLegacy) continue;
        
        // Skip the legacy prefix words themselves (e.g., @memory followed by :)
        if (/^(?:memory|mem)$/i.test(fid)) continue;
        
        // Skip if already captured
        if (fid && friendlyIds.indexOf(fid) === -1 && claimIds.indexOf(fid) === -1) {
            friendlyIds.push(fid);
        }
    }
    
    // Remove all reference patterns from text for cleanText
    var cleanText = text;
    // Remove legacy @memory:/@mem: patterns first
    cleanText = cleanText.replace(legacyRegex, '');
    // Remove only the friendly_ids we actually captured (not @memory/@mem standalone)
    for (var fi = 0; fi < friendlyIds.length; fi++) {
        // Escape special regex chars in the friendly_id (hyphens in particular)
        var escapedFid = friendlyIds[fi].replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
        var removeRegex = new RegExp('(^|\\s)@' + escapedFid + '(?=\\s|$)', 'g');
        cleanText = cleanText.replace(removeRegex, '$1');
    }
    cleanText = cleanText.replace(/\s+/g, ' ').trim();
    
    return {
        cleanText: cleanText,
        claimIds: claimIds,
        friendlyIds: friendlyIds
    };
}

// Test function for parseMemoryReferences
function testParseMemoryReferences() {
    var testCases = [
        // Legacy @memory:/@mem: patterns
        { 
            input: "Please consider @memory:abc123 this fact", 
            expected: { cleanText: "Please consider this fact", claimIds: ["abc123"], friendlyIds: [] }
        },
        { 
            input: "@mem:fact-1 and @memory:fact-2 are relevant", 
            expected: { cleanText: "and are relevant", claimIds: ["fact-1", "fact-2"], friendlyIds: [] }
        },
        { 
            input: "No references here", 
            expected: { cleanText: "No references here", claimIds: [], friendlyIds: [] }
        },
        { 
            input: "@memory:a1b2c3d4-e5f6-7890-abcd-ef1234567890 with UUID", 
            expected: { cleanText: "with UUID", claimIds: ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"], friendlyIds: [] }
        },
        { 
            input: "@memory:same @memory:same duplicate", 
            expected: { cleanText: "duplicate", claimIds: ["same"], friendlyIds: [] }
        },
        // Friendly ID patterns: with underscores (claim-style)
        {
            input: "Check @prefer_morning_a3f2 for details",
            expected: { cleanText: "Check for details", claimIds: [], friendlyIds: ["prefer_morning_a3f2"] }
        },
        // Friendly ID patterns: short without underscores (context-style)
        {
            input: "@ssdva what are the claims",
            expected: { cleanText: "what are the claims", claimIds: [], friendlyIds: ["ssdva"] }
        },
        // Mixed: claim friendly_id + context friendly_id
        {
            input: "@in_2020_at_age_1vqt @ssdva what are the claims",
            expected: { cleanText: "what are the claims", claimIds: [], friendlyIds: ["in_2020_at_age_1vqt", "ssdva"] }
        },
        // Mixed: legacy + friendly_id (claim + context)
        {
            input: "@memory:uuid123 @work_context_a3b2 @myctx tell me about them",
            expected: { cleanText: "tell me about them", claimIds: ["uuid123"], friendlyIds: ["work_context_a3b2", "myctx"] }
        },
        // Should NOT match: email addresses (@ preceded by non-whitespace)
        {
            input: "Send to user@domain.com please",
            expected: { cleanText: "Send to user@domain.com please", claimIds: [], friendlyIds: [] }
        },
        // Should NOT match: too short (1-2 chars after @)
        {
            input: "Hey @ab what's up",
            expected: { cleanText: "Hey @ab what's up", claimIds: [], friendlyIds: [] }
        },
        // Should match: exactly 3 chars
        {
            input: "Check @abc for info",
            expected: { cleanText: "Check for info", claimIds: [], friendlyIds: ["abc"] }
        },
        // Should NOT match: @memory and @mem as standalone words (legacy prefixes)
        {
            input: "@memory is a system @mem is short",
            expected: { cleanText: "@memory is a system @mem is short", claimIds: [], friendlyIds: [] }
        }
    ];
    
    var failures = 0;
    testCases.forEach(function(testCase, index) {
        var result = parseMemoryReferences(testCase.input);
        var passed = true;
        
        if (result.cleanText !== testCase.expected.cleanText) {
            console.error('Test ' + (index + 1) + ' FAILED cleanText. Expected: "' + testCase.expected.cleanText + '", Got: "' + result.cleanText + '"');
            passed = false;
        }
        
        if (JSON.stringify(result.claimIds.sort()) !== JSON.stringify(testCase.expected.claimIds.sort())) {
            console.error('Test ' + (index + 1) + ' FAILED claimIds. Expected: ' + JSON.stringify(testCase.expected.claimIds) + ', Got: ' + JSON.stringify(result.claimIds));
            passed = false;
        }
        
        if (JSON.stringify(result.friendlyIds.sort()) !== JSON.stringify(testCase.expected.friendlyIds.sort())) {
            console.error('Test ' + (index + 1) + ' FAILED friendlyIds. Expected: ' + JSON.stringify(testCase.expected.friendlyIds) + ', Got: ' + JSON.stringify(result.friendlyIds));
            passed = false;
        }
        
        if (passed) {
            console.log('Test ' + (index + 1) + ' PASSED: "' + testCase.input.substring(0, 50) + '..."');
        } else {
            failures++;
            console.log('Test ' + (index + 1) + ' result:', result);
        }
    });
    
    console.log("Memory reference parsing tests completed. " + (failures > 0 ? failures + " FAILURES" : "All passed."));
}

// testParseMemoryReferences();