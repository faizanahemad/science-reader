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
testParseMessageForCheckBoxes(); 


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
testParseMessageForCheckBoxesV2();

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

comprehensiveTestParseMessageForCheckBoxes();


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

comprehensiveTestParseMessageForCheckBoxesV2();