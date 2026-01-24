```
function extractLeetCodeProblemData(element) {
    try {
        // Handle both string HTML and DOM elements
        let problemElement;
        if (typeof element === 'string') {
            const parser = new DOMParser();
            const doc = parser.parseFromString(element, 'text/html');
            problemElement = doc.querySelector('a');
        } else {
            problemElement = element;
        }
        
        if (!problemElement) {
            throw new Error('Problem element not found');
        }

        // Extract href and construct URL
        const href = problemElement.getAttribute('href');
        if (!href) {
            throw new Error('Problem href not found');
        }
        
        // Parse URL parameters
        const urlParams = new URLSearchParams(href.split('?')[1] || '');
        const company = urlParams.get('envId') || null;
        const envType = urlParams.get('envType') || null;
        const favoriteSlug = urlParams.get('favoriteSlug') || null;
        
        // Extract problem slug from URL path
        const pathMatch = href.match(/\/problems\/([^?]+)/);
        const slug = pathMatch ? pathMatch[1] : null;
        
        // Construct full URL
        const problemUrl = href.startsWith('http') ? href : `https://leetcode.com${href}`;

        // Extract Problem ID and Title
        const titleElement = problemElement.querySelector('.ellipsis.line-clamp-1');
        let problemId = null;
        let problemTitle = '';
        let fullTitle = '';
        
        if (titleElement) {
            fullTitle = titleElement.textContent.trim();
            const titleMatch = fullTitle.match(/^(\d+)\.\s*(.+)$/);
            if (titleMatch) {
                problemId = parseInt(titleMatch[1]);
                problemTitle = titleMatch[2];
            } else {
                problemTitle = fullTitle;
            }
        }

        // Extract Acceptance Rate
        const acceptanceElement = problemElement.querySelector('.text-sd-muted-foreground.flex.w-\\[70px\\]');
        let acceptanceRate = null;
        let acceptanceRateNumeric = null;
        
        if (acceptanceElement) {
            const acceptanceText = acceptanceElement.textContent.trim();
            acceptanceRate = acceptanceText;
            const rateMatch = acceptanceText.match(/(\d+\.?\d*)%/);
            acceptanceRateNumeric = rateMatch ? parseFloat(rateMatch[1]) : null;
        }

        // Extract Difficulty
        let difficulty = 'Unknown';
        let difficultyColor = null;
        const difficultyElement = problemElement.querySelector('p[class*="text-sd-"]');
        
        if (difficultyElement) {
            difficulty = difficultyElement.textContent.trim();
            const classList = difficultyElement.className;
            
            if (classList.includes('text-sd-easy')) {
                difficultyColor = 'green';
            } else if (classList.includes('text-sd-medium')) {
                difficultyColor = 'orange';
            } else if (classList.includes('text-sd-hard')) {
                difficultyColor = 'red';
            }
        }

        // Extract Frequency (count visible bars without opacity-40)
        let frequency = 0;
        let maxFrequency = 0;
        const frequencyContainer = problemElement.querySelector('.flex.gap-0\\.5.px-1');
        
        if (frequencyContainer) {
            const bars = frequencyContainer.querySelectorAll('.bg-brand-orange');
            maxFrequency = bars.length;
            
            bars.forEach(bar => {
                // Count only bars that don't have opacity-40 class
                if (!bar.classList.contains('opacity-40')) {
                    frequency++;
                }
            });
        }

        // Check if problem is favorited (star icon)
        const starIcon = problemElement.querySelector('svg[data-icon="star"]');
        const isFavorited = !!starIcon;

        return {
            id: problemId,
            title: problemTitle,
            fullTitle: fullTitle,
            slug: slug,
            url: problemUrl,
            acceptance: acceptanceRate,
            acceptanceNumeric: acceptanceRateNumeric,
            difficulty: difficulty,
            difficultyColor: difficultyColor,
            frequency: frequency,
            maxFrequency: maxFrequency || 8, // Default to 8 if not found
            company: company,
            envType: envType,
            favoriteSlug: favoriteSlug,
            isFavorited: isFavorited,
            extractedAt: new Date().toISOString()
        };

    } catch (error) {
        console.error('Error extracting problem data:', error);
        return {
            error: error.message,
            element: element?.outerHTML?.substring(0, 200) || 'Unknown element',
            extractedAt: new Date().toISOString()
        };
    }
}

function extractAllLeetCodeProblems(containerSelector = null) {
    try {
        // Try multiple approaches to find the container
        let containerElement = null;
        
        // First, try the provided selector
        if (containerSelector) {
            if (typeof containerSelector === 'string') {
                containerElement = document.querySelector(containerSelector);
            } else if (containerSelector instanceof HTMLElement) {
                containerElement = containerSelector;
            }
        }
        
        // If no container found, try various selectors
        if (!containerElement) {
            const selectors = [
                // Try the specific selector you provided (with proper escaping)
                '.absolute.left-0.top-0.w-full.pb-\\[80px\\]',
                // Try finding the container with problem links
                'div:has(> a[href*="/problems/"])',
                // Try finding by the structure
                'div.w-full.flex-1 > div > div > div',
                // More generic approaches
                '[class*="absolute"][class*="left-0"][class*="top-0"][class*="pb-"]',
                'div[class*="pb-\\[80px\\]"]'
            ];
            
            for (const selector of selectors) {
                try {
                    containerElement = document.querySelector(selector);
                    if (containerElement) {
                        console.log(`Found container using selector: ${selector}`);
                        break;
                    }
                } catch (e) {
                    // Some selectors might not be supported in all browsers
                    continue;
                }
            }
        }
        
        // If still no container, search for problem links directly
        let problemLinks;
        if (containerElement) {
            problemLinks = containerElement.querySelectorAll('a[href*="/problems/"][id]');
        } else {
            console.warn('Container not found, searching entire document for problem links');
            // Look for problem links with the specific structure
            problemLinks = document.querySelectorAll('a[href*="/problems/"][id]');
        }
        
        if (problemLinks.length === 0) {
            // Try without the id attribute requirement
            problemLinks = containerElement 
                ? containerElement.querySelectorAll('a[href*="/problems/"]')
                : document.querySelectorAll('a[href*="/problems/"]');
        }
        
        if (problemLinks.length === 0) {
            console.warn('No problem links found');
            return {
                problems: [],
                metadata: {
                    totalFound: 0,
                    successfullyExtracted: 0,
                    errors: ['No problem links found'],
                    extractedAt: new Date().toISOString(),
                    containerFound: !!containerElement
                }
            };
        }
        
        console.log(`Found ${problemLinks.length} problem links`);
        
        // Extract data from each problem
        const problemsData = [];
        const errors = [];
        
        problemLinks.forEach((link, index) => {
            try {
                // Make sure this is a valid problem link (has the expected structure)
                if (link.querySelector('.ellipsis.line-clamp-1')) {
                    const problemData = extractLeetCodeProblemData(link);
                    
                    if (problemData && !problemData.error) {
                        problemData.batchIndex = index;
                        problemsData.push(problemData);
                    } else if (problemData && problemData.error) {
                        errors.push({
                            index,
                            error: problemData.error
                        });
                    }
                }
            } catch (error) {
                errors.push({
                    index,
                    error: error.message
                });
                console.warn(`Error extracting problem at index ${index}:`, error);
            }
        });
        
        // Log summary
        console.log(`Successfully extracted ${problemsData.length} problems`);
        if (errors.length > 0) {
            console.warn(`Encountered ${errors.length} errors during extraction`);
        }
        
        return {
            problems: problemsData,
            metadata: {
                totalFound: problemLinks.length,
                successfullyExtracted: problemsData.length,
                errors: errors,
                extractedAt: new Date().toISOString(),
                containerFound: !!containerElement
            }
        };
        
    } catch (error) {
        console.error('Error in batch extraction:', error);
        return {
            problems: [],
            metadata: {
                totalFound: 0,
                successfullyExtracted: 0,
                errors: [{ error: error.message }],
                extractedAt: new Date().toISOString()
            }
        };
    }
}

// Helper function to export data as CSV
function exportToCSV(data) {
    if (!data.problems || data.problems.length === 0) {
        console.warn('No problems to export');
        return;
    }
    
    const headers = ['ID', 'Title', 'Difficulty', 'Acceptance Rate', 'Frequency', 'URL'];
    const rows = data.problems.map(p => [
        p.id || '',
        p.title || '',
        p.difficulty || '',
        p.acceptanceNumeric || '',
        `${p.frequency}/${p.maxFrequency}`,
        p.url || ''
    ]);
    
    const csvContent = [
        headers.join(','),
        ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
    ].join('\n');
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `leetcode_problems_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

function convertToMarkdownTable(problemsData, options = {}) {  
    const defaultOptions = {  
        includeMetadata: true,  
        maxTitleLength: 50,  
        dateFormat: 'en-US',  
        includeProgress: true,  
        sortBy: null, // Removed default sorting to maintain extraction order  
        sortOrder: 'asc'  
    };  
      
    const config = { ...defaultOptions, ...options };  
      
    // Helper function to generate metadata section  
    function generateMetadataSection(data) {  
        if (!config.includeMetadata || !data.metadata) return '';  
          
        const meta = data.metadata;  
        const successRate = meta.totalFound > 0 ?   
            ((meta.successfullyExtracted / meta.totalFound) * 100).toFixed(1) : '0.0';  
          
        return `## **LeetCode Problems Extraction Summary**  
  
| **Metric** | **Value** |  
|------------|-----------|  
| **Total Found** | ${meta.totalFound} |  
| **Successfully Extracted** | ${meta.successfullyExtracted} |  
| **Errors** | ${meta.errors} |  
| **Extraction Date** | ${meta.extractionDate} |  
| **Success Rate** | ${successRate}% |  
  
---  
  
`;  
    }  
      
    // Helper function to format difficulty with proper indicators  
    function formatDifficulty(difficulty) {  
        const indicators = {  
            'Easy': '🟢 Easy',  
            'Medium': '🟠 Med.', // Orange circle for medium  
            'Hard': '🔴 Hard'  
        };  
        return indicators[difficulty] || difficulty;  
    }  
      
    // Helper function to format problem title  
    function formatProblemTitle(id, title) {  
        const truncatedTitle = config.maxTitleLength && title.length > config.maxTitleLength  
            ? title.substring(0, config.maxTitleLength) + '...'  
            : title;  
        return `${id}. ${truncatedTitle}`;  
    }  
      
    // Helper function to format frequency as number out of 8  
    function formatFrequency(frequency, maxFrequency = 8) {  
        return `${frequency}/${maxFrequency}`;  
    }  
      
    // Generate table header (removed Company and Star columns)  
    function generateTableHeader() {  
        return '| **Problem** | **Difficulty** | **Acceptance** | **Frequency** | **Link** |';  
    }  
      
    // Generate table separator  
    function generateTableSeparator() {  
        return '|-------------|----------------|----------------|---------------|----------|';  
    }  
      
    // Generate table rows  
    function generateTableRows(problems) {  
        return problems  
            .filter(problem => !problem.error) // Filter out errors  
            .map(problem => {  
                const formattedTitle = formatProblemTitle(problem.id, problem.title);  
                const formattedDifficulty = formatDifficulty(problem.difficulty);  
                const acceptance = problem.acceptance ? `${problem.acceptance}%` : 'N/A';  
                const frequency = formatFrequency(problem.frequency, problem.maxFrequency);  
                const link = `[🔗](${problem.url})`;  
                  
                return `| ${formattedTitle} | ${formattedDifficulty} | ${acceptance} | ${frequency} | ${link} |`;  
            })  
            .join('\n');  
    }  
      
    // Main function logic  
    const problems = Array.isArray(problemsData) ? problemsData : problemsData.problems || [];  
      
    // **NO SORTING** - Maintain extraction order as requested  
    const processedProblems = problems;  
      
    // Generate markdown components  
    const metadataSection = generateMetadataSection(problemsData);  
    const tableHeader = generateTableHeader();  
    const tableSeparator = generateTableSeparator();  
    const tableRows = generateTableRows(processedProblems);  
      
    // Combine all parts  
    const markdownTable = [  
        metadataSection,  
        tableHeader,  
        tableSeparator,  
        tableRows  
    ].filter(Boolean).join('\n');  
      
    return markdownTable;  
}  


// Usage example:
// const result = extractAllLeetCodeProblems();
// console.log(result);
// exportToCSV(result);
// convertToMarkdownTable(result);
```