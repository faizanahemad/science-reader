/**
 * Extractor Core — Shared Extraction Engine
 *
 * Purpose:
 *   Provides the page content extraction engine, scroll detection system,
 *   capture context management, and page metrics used by all extensions.
 *   This file is shared across extensions via symlinks.
 *
 * Contents:
 *   - extractPageContent() dispatcher + 15+ site-specific extractors + generic fallback
 *   - buildResult() helper, getSelectedText()
 *   - getPageMetrics(), scrollToPosition() for full-page capture
 *   - 5-stage scroll target detection pipeline (findScrollTarget)
 *   - Capture context management (init, scroll, metrics, release)
 *   - quickActionRequest() — API call only (no UI rendering)
 *   - chrome.runtime.onMessage handler for CORE message types only
 *
 * Exports (on window.__extractorCore):
 *   extractPageContent, getSelectedText, getPageMetrics, scrollToPosition,
 *   quickActionRequest, initCaptureContext, scrollContextTo, getContextMetrics,
 *   releaseCaptureContext, findScrollTarget
 *
 * Load order: This file MUST load before extractor-ui.js (enforced by manifest).
 */

(function() {
    'use strict';

    // Prevent multiple injections
    if (window.__aiAssistantInjected) return;
    window.__aiAssistantInjected = true;

    console.log('[AI Assistant] Content script loaded');

    // ==================== Page Content Extraction ====================

    /**
     * Extract readable content from the page
     * Uses heuristics and site-specific extractors
     */
    function extractPageContent() {
        try {
            // First, check if user has selected text - use that preferentially
            const selection = window.getSelection();
            const selectedText = selection ? selection.toString().trim() : '';
            
            if (selectedText.length > 100) {
                console.log('[AI Assistant] Using selected text:', selectedText.length, 'chars');
                return {
                    title: document.title,
                    url: window.location.href,
                    content: `**Selected Text:**\n\n${selectedText}`,
                    meta: 'User selection',
                    length: selectedText.length,
                    isSelection: true
                };
            }
            
            const hostname = window.location.hostname;
            
            // Site-specific extraction for known sites
            if (hostname.includes('news.ycombinator.com')) {
                return extractHackerNews();
            }
            if (hostname.includes('reddit.com')) {
                return extractReddit();
            }
            if (hostname.includes('docs.google.com')) {
                return extractGoogleDocs();
            }
            if (hostname.includes('sheets.google.com')) {
                return extractGoogleSheets();
            }
            if (hostname.includes('mail.google.com')) {
                return extractGmail();
            }
            if (hostname.includes('twitter.com') || hostname.includes('x.com')) {
                return extractTwitter();
            }
            if (hostname.includes('quip.com')) {
                return extractQuip();
            }
            if (hostname.includes('linkedin.com')) {
                return extractLinkedIn();
            }
            if (hostname.includes('github.com')) {
                return extractGitHub();
            }
            if (hostname.includes('medium.com') || hostname.includes('substack.com')) {
                return extractMediumSubstack();
            }
            if (hostname.includes('youtube.com')) {
                return extractYouTube();
            }
            if (hostname.includes('wikipedia.org')) {
                return extractWikipedia();
            }
            if (hostname.includes('stackoverflow.com') || hostname.includes('stackexchange.com')) {
                return extractStackOverflow();
            }
            if (hostname.includes('notion.so') || hostname.includes('notion.site')) {
                return extractNotion();
            }
            
            // Generic extraction for other sites
            return extractGenericPage();
        } catch (error) {
            console.error('[AI Assistant] Extraction error:', error);
            return {
                title: document.title,
                url: window.location.href,
                content: `Error extracting content: ${error.message}. Falling back to basic extraction.\n\n${document.body?.innerText?.substring(0, 50000) || 'No content available'}`,
                meta: 'Extraction error - used fallback',
                length: 0,
                error: error.message
            };
        }
    }
    
    // ==================== Site-Specific Extractors ====================
    
    /**
     * Extract Hacker News content
     */
    function extractHackerNews() {
        const parts = [];
        
        // Get story title and link
        const titleLink = document.querySelector('.titleline > a');
        if (titleLink) {
            parts.push(`**Story Title:** ${titleLink.textContent}`);
            parts.push(`**Link:** ${titleLink.href}`);
        }
        
        // Get story subtext (points, author, time)
        const subtext = document.querySelector('.subtext');
        if (subtext) {
            parts.push(`**Info:** ${subtext.textContent.trim()}`);
        }
        
        parts.push('\n**Comments:**\n');
        
        // Get all comments
        const comments = document.querySelectorAll('.commtext');
        comments.forEach((comment) => {
            const indent = comment.closest('.comment')?.querySelector('.ind img')?.width || 0;
            const depth = Math.floor(indent / 40);
            const prefix = '  '.repeat(depth) + (depth > 0 ? '↳ ' : '');
            
            const row = comment.closest('tr');
            const author = row?.previousElementSibling?.querySelector('.hnuser')?.textContent || 'unknown';
            
            const text = comment.textContent.trim();
            if (text) {
                parts.push(`${prefix}[${author}]: ${text}\n`);
            }
        });
        
        return buildResult(parts.join('\n'), 'Hacker News discussion');
    }
    
    /**
     * Extract Reddit content
     */
    function extractReddit() {
        const parts = [];
        
        // New Reddit
        const title = document.querySelector('[data-testid="post-title"]') || 
                     document.querySelector('h1[slot="title"]') ||
                     document.querySelector('h1');
        if (title) {
            parts.push(`**Post Title:** ${title.textContent.trim()}`);
        }
        
        // Post content (self-text)
        const postContent = document.querySelector('[data-testid="post-content"]') ||
                           document.querySelector('[slot="text-body"]') ||
                           document.querySelector('.post-content') ||
                           document.querySelector('[data-click-id="text"]');
        if (postContent) {
            parts.push(`\n**Post Content:**\n${postContent.textContent.trim()}`);
        }
        
        parts.push('\n\n**Comments:**\n');
        
        // Get comments - try multiple selectors for different Reddit versions
        const commentSelectors = [
            'shreddit-comment',
            '[data-testid="comment"]',
            '.Comment',
            '.thing.comment'
        ];
        
        for (const selector of commentSelectors) {
            const comments = document.querySelectorAll(selector);
            if (comments.length > 0) {
                comments.forEach((comment) => {
                    const author = comment.getAttribute('author') ||
                                  comment.querySelector('[data-testid="comment_author_link"]')?.textContent ||
                                  comment.querySelector('.author')?.textContent || 'unknown';
                    
                    const text = comment.querySelector('[slot="comment"]')?.textContent ||
                                comment.querySelector('[data-testid="comment-body"]')?.textContent ||
                                comment.querySelector('.md')?.textContent;
                    
                    if (text) {
                        parts.push(`[${author}]: ${text.trim()}\n`);
                    }
                });
                break;
            }
        }
        
        return buildResult(parts.join('\n'), 'Reddit discussion');
    }
    
    /**
     * Extract Google Docs content
     * Uses multiple strategies, falls back to screenshot for canvas-based rendering
     */
    function extractGoogleDocs() {
        const parts = [];
        parts.push(`**Document:** ${document.title}`);
        
        // Check for user selection first
        const selection = window.getSelection();
        const selectedText = selection ? selection.toString().trim() : '';
        if (selectedText.length > 50) {
            return {
                title: document.title,
                url: window.location.href,
                content: `**Document:** ${document.title}\n\n**Selected Text:**\n${selectedText}`,
                meta: 'Google Docs (selected text)',
                length: selectedText.length,
                isSelection: true
            };
        }
        
        // Strategy 1: Try to get word nodes (most reliable for new Docs)
        const wordNodes = document.querySelectorAll('.kix-wordhtmlgenerator-word-node');
        if (wordNodes.length > 0) {
            let currentParagraph = [];
            let lastTop = null;
            
            wordNodes.forEach(node => {
                const rect = node.getBoundingClientRect();
                if (lastTop !== null && Math.abs(rect.top - lastTop) > 10) {
                    if (currentParagraph.length > 0) {
                        parts.push(currentParagraph.join(''));
                        currentParagraph = [];
                    }
                }
                currentParagraph.push(node.textContent);
                lastTop = rect.top;
            });
            if (currentParagraph.length > 0) {
                parts.push(currentParagraph.join(''));
            }
        }
        
        // Strategy 2: Try paragraph renderers
        if (parts.length <= 1) {
            const paragraphs = document.querySelectorAll('.kix-paragraphrenderer');
            paragraphs.forEach(p => {
                const text = p.textContent.trim();
                if (text) parts.push(text);
            });
        }
        
        // Strategy 3: Try line views
        if (parts.length <= 1) {
            const lines = document.querySelectorAll('.kix-lineview');
            lines.forEach(line => {
                const text = line.textContent.trim();
                if (text) parts.push(text);
            });
        }
        
        // Strategy 4: Get any text from the editor area
        if (parts.length <= 1) {
            const editorArea = document.querySelector('.kix-appview-editor');
            if (editorArea) {
                const walker = document.createTreeWalker(
                    editorArea,
                    NodeFilter.SHOW_TEXT,
                    null,
                    false
                );
                
                let node;
                while (node = walker.nextNode()) {
                    const text = node.textContent.trim();
                    if (text && text.length > 1) {
                        parts.push(text);
                    }
                }
            }
        }
        
        let content = parts.filter(p => p.length > 0).join('\n\n');
        
        // Detect if extracted text is just UI chrome (toolbar, page indicators, etc.)
        // rather than actual document content. Google Docs toolbar/menu text can
        // easily exceed 100 chars, giving false positives.
        var chromePatterns = /^(gemini|drag image|how gemini|of \d+|\d+ of \d+|page \d+|heading|normal text|arial|verdana|file|edit|view|insert|format|tools|extensions|help|share|starred|move|see document status|last edit|menus|editing|suggesting|viewing)/i;
        var meaningfulParts = parts.filter(function(p) {
            var trimmed = p.trim();
            return trimmed.length > 20 && !chromePatterns.test(trimmed);
        });
        var meaningfulContent = meaningfulParts.join('\n\n');
        
        if (meaningfulContent.length < 500) {
            return {
                title: document.title,
                url: window.location.href,
                content: '',
                meta: 'Google Docs',
                length: 0,
                needsScreenshot: true,
                canvasApp: true,
                instructions: 'Google Docs uses canvas rendering. Please select text with Ctrl+A/Cmd+A and try again, or paste the content directly in chat.'
            };
        }
        
        return buildResult(content, 'Google Docs');
    }
    
    /**
     * Extract Google Sheets content
     */
    function extractGoogleSheets() {
        const parts = [];
        parts.push(`**Spreadsheet:** ${document.title}`);
        
        // Get sheet name
        const sheetName = document.querySelector('.docs-sheet-active-tab .docs-sheet-tab-name');
        if (sheetName) {
            parts.push(`**Active Sheet:** ${sheetName.textContent}`);
        }
        
        // Try to get cell content
        const cells = document.querySelectorAll('.cell-input');
        if (cells.length > 0) {
            parts.push('\n**Cell Contents:**');
            cells.forEach((cell, i) => {
                const text = cell.textContent.trim();
                if (text) parts.push(`Cell ${i + 1}: ${text}`);
            });
        }
        
        // Get from grid (visible cells)
        const gridCells = document.querySelectorAll('[role="gridcell"]');
        if (gridCells.length > 0 && parts.length <= 2) {
            parts.push('\n**Visible Data:**');
            let currentRow = '';
            let prevTop = null;
            
            gridCells.forEach(cell => {
                const rect = cell.getBoundingClientRect();
                if (prevTop !== null && Math.abs(rect.top - prevTop) > 5) {
                    if (currentRow) parts.push(currentRow);
                    currentRow = '';
                }
                const text = cell.textContent.trim();
                if (text) currentRow += text + '\t';
                prevTop = rect.top;
            });
            if (currentRow) parts.push(currentRow);
        }
        
        let content = parts.join('\n');
        
        if (content.length < 300) {
            content += '\n\n**Note:** Google Sheets has limited DOM-based extraction. For best results, select cells and use "Ask about selection" or export data.';
        }
        
        return buildResult(content, 'Google Sheets');
    }
    
    /**
     * Extract Gmail content
     */
    function extractGmail() {
        const parts = [];
        
        // Check if viewing an email or inbox
        const emailView = document.querySelector('[role="main"] .a3s');
        
        if (emailView) {
            // Viewing an email
            const subject = document.querySelector('h2[data-thread-perm-id]') || 
                           document.querySelector('.hP');
            if (subject) {
                parts.push(`**Subject:** ${subject.textContent.trim()}`);
            }
            
            // Get sender and recipients
            const sender = document.querySelector('.gD');
            if (sender) {
                parts.push(`**From:** ${sender.getAttribute('email') || sender.textContent}`);
            }
            
            const recipients = document.querySelectorAll('.g2');
            if (recipients.length > 0) {
                parts.push(`**To:** ${Array.from(recipients).map(r => r.textContent).join(', ')}`);
            }
            
            // Get email body
            const emailBodies = document.querySelectorAll('.a3s.aiL, .a3s.aXjCH');
            emailBodies.forEach((body, i) => {
                const text = body.innerText.trim();
                if (text) {
                    if (i > 0) parts.push('\n---\n**Previous message:**');
                    parts.push(`\n${text}`);
                }
            });
        } else {
            // Inbox view - list emails
            parts.push('**Gmail Inbox View**\n');
            
            const emailRows = document.querySelectorAll('tr.zA');
            emailRows.forEach(row => {
                const sender = row.querySelector('.yX .yW span')?.textContent || '';
                const subject = row.querySelector('.y6 span')?.textContent || '';
                const snippet = row.querySelector('.y2')?.textContent || '';
                
                if (sender || subject) {
                    parts.push(`• [${sender}] ${subject} - ${snippet}`);
                }
            });
        }
        
        return buildResult(parts.join('\n'), 'Gmail');
    }
    
    /**
     * Extract Twitter/X content
     */
    function extractTwitter() {
        const parts = [];
        
        // Get main tweet or thread
        const tweets = document.querySelectorAll('[data-testid="tweet"]');
        
        tweets.forEach((tweet, i) => {
            const author = tweet.querySelector('[data-testid="User-Name"]')?.textContent || '';
            const handle = author.split('@')[1] || '';
            const displayName = author.split('@')[0] || '';
            
            const tweetText = tweet.querySelector('[data-testid="tweetText"]')?.textContent || '';
            const time = tweet.querySelector('time')?.getAttribute('datetime') || '';
            
            if (tweetText) {
                parts.push(`**@${handle || displayName}** ${time ? `(${new Date(time).toLocaleString()})` : ''}`);
                parts.push(tweetText);
                parts.push('');
            }
            
            // Get media descriptions
            const images = tweet.querySelectorAll('[data-testid="tweetPhoto"] img');
            images.forEach(img => {
                const alt = img.getAttribute('alt');
                if (alt && alt !== 'Image') {
                    parts.push(`[Image: ${alt}]`);
                }
            });
            
            // Get metrics
            const metrics = tweet.querySelector('[role="group"]');
            if (metrics) {
                const likes = tweet.querySelector('[data-testid="like"]')?.textContent || '0';
                const retweets = tweet.querySelector('[data-testid="retweet"]')?.textContent || '0';
                const replies = tweet.querySelector('[data-testid="reply"]')?.textContent || '0';
                parts.push(`💬 ${replies} | 🔄 ${retweets} | ❤️ ${likes}`);
            }
            
            parts.push('\n---\n');
        });
        
        return buildResult(parts.join('\n'), 'Twitter/X');
    }
    
    /**
     * Extract Quip content
     */
    function extractQuip() {
        const parts = [];
        parts.push(`**Document:** ${document.title}`);
        
        // Quip main content
        const content = document.querySelector('.document-content') ||
                       document.querySelector('[data-contents="true"]') ||
                       document.querySelector('.thread-pane');
        
        if (content) {
            parts.push(content.innerText);
        }
        
        // Comments/chat
        const comments = document.querySelectorAll('.thread-message, .comment');
        if (comments.length > 0) {
            parts.push('\n**Comments:**');
            comments.forEach(comment => {
                const author = comment.querySelector('.author, .thread-author')?.textContent || '';
                const text = comment.querySelector('.content, .message-text')?.textContent || '';
                if (text) parts.push(`[${author}]: ${text}`);
            });
        }
        
        return buildResult(parts.join('\n'), 'Quip');
    }
    
    /**
     * Extract LinkedIn content
     */
    function extractLinkedIn() {
        const parts = [];
        
        // Profile page
        const profileName = document.querySelector('.text-heading-xlarge');
        if (profileName) {
            parts.push(`**Profile:** ${profileName.textContent.trim()}`);
            
            const headline = document.querySelector('.text-body-medium');
            if (headline) parts.push(`**Headline:** ${headline.textContent.trim()}`);
            
            const about = document.querySelector('#about ~ div .inline-show-more-text');
            if (about) parts.push(`\n**About:**\n${about.textContent.trim()}`);
        }
        
        // Post/article
        const posts = document.querySelectorAll('.feed-shared-update-v2, .occludable-update');
        posts.forEach(post => {
            const author = post.querySelector('.update-components-actor__name')?.textContent?.trim() || '';
            const content = post.querySelector('.feed-shared-update-v2__description, .break-words')?.textContent?.trim() || '';
            if (content) {
                parts.push(`\n**${author}:**\n${content}\n`);
            }
        });
        
        return buildResult(parts.join('\n'), 'LinkedIn');
    }
    
    /**
     * Extract GitHub content
     */
    function extractGitHub() {
        const parts = [];
        
        // Repository README
        const readme = document.querySelector('.markdown-body.entry-content');
        if (readme) {
            parts.push(`**Repository:** ${document.title.split(' ·')[0]}`);
            parts.push(`\n**README:**\n${readme.innerText}`);
        }
        
        // Issue/PR
        const issueTitle = document.querySelector('.js-issue-title');
        if (issueTitle) {
            parts.push(`**Issue/PR:** ${issueTitle.textContent.trim()}`);
            
            const body = document.querySelector('.comment-body');
            if (body) parts.push(`\n**Description:**\n${body.innerText}`);
            
            // Comments
            const comments = document.querySelectorAll('.timeline-comment');
            comments.forEach(comment => {
                const author = comment.querySelector('.author')?.textContent || '';
                const text = comment.querySelector('.comment-body')?.innerText || '';
                if (text) parts.push(`\n**[${author}]:**\n${text}`);
            });
        }
        
        // Code file
        const codeContent = document.querySelector('.blob-wrapper');
        if (codeContent && !readme) {
            const fileName = document.querySelector('.final-path')?.textContent || '';
            parts.push(`**File:** ${fileName}`);
            parts.push(`\n\`\`\`\n${codeContent.innerText}\n\`\`\``);
        }
        
        return buildResult(parts.join('\n'), 'GitHub');
    }
    
    /**
     * Extract Medium/Substack content
     */
    function extractMediumSubstack() {
        const parts = [];
        
        // Title
        const title = document.querySelector('h1');
        if (title) parts.push(`**Title:** ${title.textContent.trim()}`);
        
        // Author
        const author = document.querySelector('[rel="author"], .author-name, .post-meta a');
        if (author) parts.push(`**Author:** ${author.textContent.trim()}`);
        
        // Article content
        const article = document.querySelector('article') ||
                       document.querySelector('.post-content') ||
                       document.querySelector('.markup');
        if (article) {
            // Clone and clean
            const clone = article.cloneNode(true);
            clone.querySelectorAll('script, style, .image-caption').forEach(el => el.remove());
            parts.push(`\n${clone.innerText}`);
        }
        
        return buildResult(parts.join('\n'), 'Article');
    }
    
    /**
     * Extract YouTube content
     */
    function extractYouTube() {
        const parts = [];
        
        // Video title
        const title = document.querySelector('h1.ytd-video-primary-info-renderer, h1.ytd-watch-metadata');
        if (title) parts.push(`**Video:** ${title.textContent.trim()}`);
        
        // Channel
        const channel = document.querySelector('#channel-name a, ytd-channel-name a');
        if (channel) parts.push(`**Channel:** ${channel.textContent.trim()}`);
        
        // Description
        const description = document.querySelector('#description-inline-expander, #description');
        if (description) parts.push(`\n**Description:**\n${description.innerText.trim()}`);
        
        // Comments
        const comments = document.querySelectorAll('ytd-comment-thread-renderer');
        if (comments.length > 0) {
            parts.push('\n**Top Comments:**');
            Array.from(comments).slice(0, 10).forEach(comment => {
                const author = comment.querySelector('#author-text')?.textContent?.trim() || '';
                const text = comment.querySelector('#content-text')?.textContent?.trim() || '';
                if (text) parts.push(`[${author}]: ${text}`);
            });
        }
        
        // Transcript (if available)
        const transcript = document.querySelector('.ytd-transcript-segment-list-renderer');
        if (transcript) {
            parts.push('\n**Transcript:**');
            parts.push(transcript.innerText);
        }
        
        return buildResult(parts.join('\n'), 'YouTube');
    }
    
    /**
     * Extract Wikipedia content
     */
    function extractWikipedia() {
        const parts = [];
        
        // Title
        const title = document.querySelector('#firstHeading');
        if (title) parts.push(`**${title.textContent.trim()}**\n`);
        
        // Article content
        const content = document.querySelector('#mw-content-text .mw-parser-output');
        if (content) {
            const clone = content.cloneNode(true);
            // Remove infobox, references, navboxes, etc.
            clone.querySelectorAll('.infobox, .navbox, .reflist, .mw-editsection, .reference, .thumb, .toc, script, style').forEach(el => el.remove());
            parts.push(clone.innerText);
        }
        
        return buildResult(parts.join('\n'), 'Wikipedia');
    }
    
    /**
     * Extract Stack Overflow content
     */
    function extractStackOverflow() {
        const parts = [];
        
        // Question
        const questionTitle = document.querySelector('#question-header h1');
        if (questionTitle) parts.push(`**Question:** ${questionTitle.textContent.trim()}`);
        
        const questionBody = document.querySelector('.question .s-prose');
        if (questionBody) parts.push(`\n${questionBody.innerText}`);
        
        // Tags
        const tags = document.querySelectorAll('.question .post-tag');
        if (tags.length > 0) {
            parts.push(`\n**Tags:** ${Array.from(tags).map(t => t.textContent).join(', ')}`);
        }
        
        // Answers
        const answers = document.querySelectorAll('.answer');
        answers.forEach((answer, i) => {
            const isAccepted = answer.classList.contains('accepted-answer');
            const votes = answer.querySelector('.js-vote-count')?.textContent || '0';
            const body = answer.querySelector('.s-prose')?.innerText || '';
            
            parts.push(`\n---\n**Answer ${i + 1}** ${isAccepted ? '✓ Accepted' : ''} (${votes} votes):\n${body}`);
        });
        
        return buildResult(parts.join('\n'), 'Stack Overflow');
    }
    
    /**
     * Extract Notion content
     */
    function extractNotion() {
        const parts = [];
        parts.push(`**Page:** ${document.title}`);
        
        // Main content
        const content = document.querySelector('.notion-page-content') ||
                       document.querySelector('[data-content-editable-root="true"]') ||
                       document.querySelector('.notion-frame');
        
        if (content) {
            // Get all text blocks
            const blocks = content.querySelectorAll('[data-block-id]');
            blocks.forEach(block => {
                const text = block.innerText?.trim();
                if (text && text.length > 0) {
                    parts.push(text);
                }
            });
        }
        
        // Fallback
        if (parts.length <= 1) {
            const mainFrame = document.querySelector('.notion-frame');
            if (mainFrame) parts.push(mainFrame.innerText);
        }
        
        return buildResult(parts.join('\n\n'), 'Notion');
    }
    
    /**
     * Generic page extraction
     */
    function extractGenericPage() {
        // Try to find main content element
        const contentSelectors = [
            'article',
            '[role="main"]',
            'main',
            '.post-content',
            '.article-content', 
            '.entry-content',
            '.content',
            '#content',
            '.post-body',
            '.article-body',
            '.story-body',
            '.blog-post',
            '.page-content'
        ];

        let mainContent = null;
        for (const selector of contentSelectors) {
            const element = document.querySelector(selector);
            if (element && element.textContent.trim().length > 200) {
                mainContent = element;
                break;
            }
        }

        // Fallback to body
        if (!mainContent) {
            mainContent = document.body;
        }

        // Clone to avoid modifying the page
        const clone = mainContent.cloneNode(true);

        // Remove unwanted elements
        const removeSelectors = [
            'script', 'style', 'noscript', 'iframe',
            'nav', 'header', 'footer', 'aside',
            '.sidebar', '.navigation', '.menu', '.nav',
            '.advertisement', '.ad', '.ads', '.advert', '.sponsored',
            '[role="navigation"]', '[role="banner"]', '[role="complementary"]',
            '.social-share', '.share-buttons', '.related-posts',
            '.cookie-notice', '.popup', '.modal',
            '.newsletter-signup', '.subscribe-box',
            '#disqus_thread', '.fb-comments'
        ];

        removeSelectors.forEach(selector => {
            clone.querySelectorAll(selector).forEach(el => el.remove());
        });

        // Get clean text
        let text = clone.innerText || clone.textContent || '';
        
        // Normalize whitespace
        text = text
            .replace(/[\t\r]+/g, ' ')
            .replace(/\n{3,}/g, '\n\n')
            .replace(/ {2,}/g, ' ')
            .trim();

        // Limit length
        const maxLength = 100000;
        if (text.length > maxLength) {
            text = text.substring(0, maxLength) + '\n\n[Content truncated...]';
        }

        return {
            title: document.title,
            url: window.location.href,
            content: text || 'No content could be extracted from this page.',
            meta: document.querySelector('meta[name="description"]')?.content || '',
            length: text.length
        };
    }
    
    /**
     * Helper to build consistent result object
     */
    function buildResult(content, siteName) {
        // Clean up content
        content = content
            .replace(/\n{3,}/g, '\n\n')
            .replace(/[ \t]+/g, ' ')
            .trim();
            
        // Ensure some content
        if (!content || content.length < 50) {
            content = extractGenericPage().content;
        }
        
        // Truncate if too long
        const maxLength = 100000;
        if (content.length > maxLength) {
            content = content.substring(0, maxLength) + '\n\n[Content truncated...]';
        }
        
        return {
            title: document.title,
            url: window.location.href,
            content: content,
            meta: siteName,
            length: content.length
        };
    }

    /**
     * Get currently selected text
     */
    function getSelectedText() {
        const selection = window.getSelection();
        const text = selection ? selection.toString().trim() : '';
        
        return {
            text,
            hasSelection: text.length > 0
        };
    }

    /**
     * Get page scroll + viewport metrics for full-page capture.
     * @returns {Object} Page metrics including scroll and viewport sizes.
     */
    function getPageMetrics() {
        const docEl = document.documentElement;
        const body = document.body;
        const scrollHeight = Math.max(
            docEl.scrollHeight,
            body?.scrollHeight || 0
        );
        const scrollWidth = Math.max(
            docEl.scrollWidth,
            body?.scrollWidth || 0
        );
        return {
            scrollHeight,
            scrollWidth,
            viewportHeight: window.innerHeight,
            viewportWidth: window.innerWidth,
            scrollY: window.scrollY,
            scrollX: window.scrollX,
            devicePixelRatio: window.devicePixelRatio || 1,
            url: window.location.href,
            title: document.title
        };
    }

    /**
     * Scroll page to a specific Y position for screenshot stitching.
     * @param {number} y - Vertical scroll position.
     * @returns {{scrollY: number}} The new scroll position.
     */
    function scrollToPosition(y) {
        const safeY = Math.max(0, Number.isFinite(y) ? y : 0);
        window.scrollTo(0, safeY);
        return { scrollY: window.scrollY };
    }

    // ==================== Capture Context (Inner Scroll Container Support) ====================

    const SCROLLABLE_MIN_HEIGHT = 250;
    const SCROLLABLE_MIN_WIDTH = 300;
    const SCROLLABLE_MIN_OVERFLOW = 32;
    const HEURISTIC_NODE_CAP = 5000;

    /**
     * Host-specific selectors for known web apps with inner scroll containers.
     * Ordered by specificity — first match that passes isScrollableCandidate() wins.
     * Each entry: hostRe, optional pathRe, ordered selectors list.
     */
    const KNOWN_SCROLL_SELECTORS = [
        // Microsoft Office Word Online (SharePoint-hosted and office.com)
        { hostRe: /\.sharepoint\.com$|\.office\.com$|\.live\.com$|\.officeapps\.live\.com$/,
          selectors: [
            '.WACViewPanel', '#WACViewPanel',
            '[role="document"]',
            '.PageContentContainer', '#PageContentContainer',
            '.Canvas-container',
            '#WACContainer', '.WACContainer',
            '.Editor', '#editor-host'
          ]
        },
        // Microsoft Office Excel Online
        { hostRe: /\.sharepoint\.com$|\.office\.com$|\.live\.com$|\.officeapps\.live\.com$/,
          pathRe: /excel|xlsx|spreadsheet/i,
          selectors: [
            '#GridContainer', '.ewr-grid-container',
            '.ewa-grid', '#grid-container',
            '#m_excelWebRenderer_ewaCtrl_sheetContentDiv'
          ]
        },
        // Microsoft Office PowerPoint Online
        { hostRe: /\.sharepoint\.com$|\.office\.com$|\.live\.com$|\.officeapps\.live\.com$/,
          pathRe: /powerpoint|pptx|presentation/i,
          selectors: [
            '#slide-viewer-container', '.SlideViewerContainer',
            '#slide-scroll-container'
          ]
        },
        // Google Docs
        { hostRe: /docs\.google\.com$/,
          pathRe: /^\/document\//,
          selectors: ['#kix-appview', '.kix-appview-editor', '.kix-appview']
        },
        // Google Sheets
        { hostRe: /docs\.google\.com$/,
          pathRe: /^\/spreadsheets\//,
          selectors: ['#waffle-grid-container', '#waffle-viewport-container', '.waffle-scrollable-container']
        },
        // Google Slides
        { hostRe: /docs\.google\.com$/,
          pathRe: /^\/presentation\//,
          selectors: ['.punch-viewer-container', '#filmstrip-scroll-container']
        },
        // Notion
        { hostRe: /\.notion\.so$|\.notion\.site$/,
          selectors: ['.notion-scroller', '[data-scrollable="true"]', '.notion-page-content']
        },
        // Figma (limited — canvas pan, but the layers panel can scroll)
        { hostRe: /\.figma\.com$/,
          selectors: ['[data-testid="design-panel-scroll"]', '.design_panel--scrollContainer']
        },
        // Confluence (Atlassian)
        { hostRe: /\.atlassian\.net$/,
          pathRe: /\/wiki\//,
          selectors: ['#content-body', '.ak-renderer-document', '[data-testid="renderer-scroll-container"]']
        },
        // Jira
        { hostRe: /\.atlassian\.net$/,
          pathRe: /\/browse\/|\/jira\//,
          selectors: ['[data-testid="issue.views.issue-details.issue-layout.container-left"]', '#jira-issue-body']
        },
        // Slack
        { hostRe: /\.slack\.com$/,
          selectors: ['.c-virtual_list__scroll_container', '.p-workspace__primary_view_body']
        },
        // Airtable
        { hostRe: /\.airtable\.com$/,
          selectors: ['.dataRow', '.cellContainer', '.gridView .antiscroll-inner']
        },
        // Overleaf
        { hostRe: /\.overleaf\.com$/,
          selectors: ['.cm-scroller', '.pdf-viewer-inner', '#pdf-scroll-container']
        },
        // Dropbox Paper
        { hostRe: /\.dropboxpaper\.com$|paper\.dropbox\.com$/,
          selectors: ['.editor-wrapper', '.ace-content-area']
        },
        // Generic SaaS patterns — try common scroll wrapper conventions
        { hostRe: /./,
          selectors: [
            '[data-scroll-container]', '[data-scrollable="true"]',
            'main[style*="overflow"]', '.main-scroll-container',
            '[role="main"]'
          ]
        }
    ];

    /**
     * Check if an element qualifies as a scrollable container for capture.
     * Conservative checks to avoid sidebars, dropdowns, and small panels.
     *
     * @param {HTMLElement} el - Candidate element.
     * @returns {boolean} True if the element is a viable scroll target.
     */
    function isScrollableCandidate(el) {
        if (!el || el === document.body || el === document.documentElement) return false;
        try {
            var style = getComputedStyle(el);
        } catch (_) {
            return false;
        }
        if (style.display === 'none' || style.visibility === 'hidden') return false;

        var overflowY = style.overflowY;
        if (!/^(auto|scroll|overlay)$/.test(overflowY)) return false;

        var scrollableY = el.scrollHeight - el.clientHeight;
        if (scrollableY < SCROLLABLE_MIN_OVERFLOW) return false;

        var rect = el.getBoundingClientRect();
        if (rect.width < SCROLLABLE_MIN_WIDTH || rect.height < SCROLLABLE_MIN_HEIGHT) return false;
        if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= window.innerHeight || rect.left >= window.innerWidth) return false;

        return true;
    }

    /**
     * Non-destructive probe: try a tiny scrollTop bump to confirm an element is
     * actually scrollable (handles custom scrollbar libs with overflow:hidden).
     *
     * @param {HTMLElement} el - Element to probe.
     * @returns {boolean} True if scrollTop changed.
     */
    function canScrollByProbe(el) {
        try {
            var before = el.scrollTop;
            el.scrollTop = before + 1;
            var after = el.scrollTop;
            el.scrollTop = before;
            return Math.abs(after - before) > 0.5;
        } catch (_) {
            return false;
        }
    }

    /**
     * Try host-specific known selectors to find scroll target fast.
     *
     * @returns {{el: HTMLElement, description: string}|null}
     */
    function findKnownSelectorTarget() {
        var host = location.hostname;
        var pathname = location.pathname;
        for (var i = 0; i < KNOWN_SCROLL_SELECTORS.length; i++) {
            var entry = KNOWN_SCROLL_SELECTORS[i];
            if (entry.hostRe && !entry.hostRe.test(host)) continue;
            if (entry.pathRe && !entry.pathRe.test(pathname)) continue;
            for (var j = 0; j < entry.selectors.length; j++) {
                var sel = entry.selectors[j];
                try {
                    var el = document.querySelector(sel);
                    if (!el) continue;
                    if (isScrollableCandidate(el)) {
                        return { el: el, description: 'known:' + host + ':' + sel };
                    }
                    // Fallback: known selectors are trusted — try probe even if overflow:hidden
                    // (covers apps like SharePoint Word Online that use JS-driven scroll
                    //  with overflow:hidden + custom scrollbar libraries).
                    var style = getComputedStyle(el);
                    var rect = el.getBoundingClientRect();
                    var visibleAndLarge = style.display !== 'none' &&
                        style.visibility !== 'hidden' &&
                        rect.width >= SCROLLABLE_MIN_WIDTH &&
                        rect.height >= SCROLLABLE_MIN_HEIGHT &&
                        el.scrollHeight - el.clientHeight > SCROLLABLE_MIN_OVERFLOW;
                    if (visibleAndLarge && canScrollByProbe(el)) {
                        console.log('[AI Assistant] Known selector probe-scroll match:', sel);
                        return { el: el, description: 'known-probe:' + host + ':' + sel };
                    }
                } catch (_) { /* invalid selector, skip */ }
            }
        }
        return null;
    }

    /**
     * Check if the window itself is the primary scrollable target.
     *
     * @returns {boolean} True if document-level scroll is significant.
     */
    function isWindowScrollable() {
        var scrollEl = document.scrollingElement || document.documentElement;
        return (scrollEl.scrollHeight - scrollEl.clientHeight) > SCROLLABLE_MIN_OVERFLOW;
    }

    /**
     * Compute intersection of two rects (as {left, top, right, bottom}).
     */
    function intersectRect(a, b) {
        return {
            left: Math.max(a.left, b.left),
            top: Math.max(a.top, b.top),
            right: Math.min(a.right, b.right),
            bottom: Math.min(a.bottom, b.bottom)
        };
    }

    /**
     * DOM depth of an element (used as tie-breaker in scoring).
     */
    function domDepth(el) {
        var depth = 0;
        var node = el;
        while (node && node !== document.body) {
            depth++;
            node = node.parentElement;
        }
        return depth;
    }

    /**
     * Score a scrollable candidate for "how likely is this the main content area".
     * Higher is better.
     *
     * Factors:
     *   - coverage: fraction of viewport area the element covers (weight 6)
     *   - scrollFactor: how much scrollable content exists relative to its view (weight 2)
     *   - centerDist: distance from element center to viewport center, penalized (weight -0.75)
     *   - depth: DOM depth as tie-breaker (weight +0.01)
     *
     * @param {HTMLElement} el
     * @returns {number}
     */
    function scoreScrollable(el) {
        var rect = el.getBoundingClientRect();
        var vpW = window.innerWidth;
        var vpH = window.innerHeight;
        var vis = intersectRect(
            { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom },
            { left: 0, top: 0, right: vpW, bottom: vpH }
        );
        var visW = Math.max(0, vis.right - vis.left);
        var visH = Math.max(0, vis.bottom - vis.top);
        var visArea = visW * visH;
        var vpArea = vpW * vpH;
        var coverage = visArea / Math.max(1, vpArea);

        var scrollableY = Math.max(0, el.scrollHeight - el.clientHeight);
        var scrollFactor = Math.min(1, scrollableY / Math.max(1, el.clientHeight * 2));

        var elCenterX = (vis.left + vis.right) / 2;
        var elCenterY = (vis.top + vis.bottom) / 2;
        var vpCenterX = vpW / 2;
        var vpCenterY = vpH / 2;
        var maxDist = Math.sqrt(vpCenterX * vpCenterX + vpCenterY * vpCenterY);
        var dist = Math.sqrt(
            Math.pow(elCenterX - vpCenterX, 2) + Math.pow(elCenterY - vpCenterY, 2)
        );
        var centerDist = dist / Math.max(1, maxDist);

        var depth = domDepth(el);

        return (coverage * 6) + (scrollFactor * 2) - (centerDist * 0.75) + (depth * 0.01);
    }

    /**
     * Heuristic: sample viewport points, walk ancestors, score candidates.
     * Falls back to a capped TreeWalker DOM walk if sampling finds nothing.
     *
     * @returns {{el: HTMLElement, description: string}|null}
     */
    function findBestScrollTarget() {
        var SAMPLE_POINTS = [
            [0.5, 0.5], [0.5, 0.25], [0.5, 0.75],
            [0.25, 0.5], [0.75, 0.5], [0.25, 0.25],
            [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]
        ];

        var candidateSet = new Set();
        var vpW = window.innerWidth;
        var vpH = window.innerHeight;

        for (var i = 0; i < SAMPLE_POINTS.length; i++) {
            var rx = SAMPLE_POINTS[i][0];
            var ry = SAMPLE_POINTS[i][1];
            var x = Math.floor(vpW * rx);
            var y = Math.floor(vpH * ry);
            var el = document.elementFromPoint(x, y);
            while (el) {
                if (isScrollableCandidate(el)) candidateSet.add(el);
                el = el.parentElement;
            }
        }

        var candidates = Array.from(candidateSet);

        // TreeWalker fallback if sampling found nothing
        if (candidates.length === 0) {
            var walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_ELEMENT,
                null,
                false
            );
            var count = 0;
            var node;
            while ((node = walker.nextNode()) && count < HEURISTIC_NODE_CAP) {
                count++;
                if (isScrollableCandidate(node)) candidates.push(node);
            }
        }

        if (candidates.length === 0) return null;

        var bestEl = null;
        var bestScore = -Infinity;
        for (var c = 0; c < candidates.length; c++) {
            var score = scoreScrollable(candidates[c]);
            if (score > bestScore) {
                bestScore = score;
                bestEl = candidates[c];
            }
        }

        if (!bestEl) return null;

        var tag = bestEl.tagName.toLowerCase();
        var id = bestEl.id ? '#' + bestEl.id : '';
        var cls = bestEl.className && typeof bestEl.className === 'string'
            ? '.' + bestEl.className.trim().split(/\s+/).slice(0, 2).join('.')
            : '';
        return {
            el: bestEl,
            description: 'heuristic:' + tag + id + cls + ':score=' + bestScore.toFixed(2)
        };
    }

    /**
     * Full detection pipeline to find the scroll target for capture.
     *
     * Order:
     *   1. Known-selector fast path (host-specific)
     *   2. Window scrollability check
     *   3. Heuristic viewport sampling + scoring
     *   4. Probe fallback for overflow:hidden custom-scrollbar elements
     *
     * @returns {{kind: string, el: HTMLElement|null, description: string}}
     *   kind: 'window' | 'element' | 'none'
     */
    function findScrollTarget() {
        // Stage 1: known selectors
        var known = findKnownSelectorTarget();
        if (known) {
            console.log('[AI Assistant] findScrollTarget stage1 MATCH:', known.description);
            return { kind: 'element', el: known.el, description: known.description };
        }
        console.log('[AI Assistant] findScrollTarget stage1: no known selector matched');

        // Stage 2: window scrollable?
        if (isWindowScrollable()) {
            console.log('[AI Assistant] findScrollTarget stage2: window is scrollable');
            return { kind: 'window', el: null, description: 'window:scrollingElement' };
        }
        console.log('[AI Assistant] findScrollTarget stage2: window NOT scrollable');

        // Stage 3: heuristic
        var heuristic = findBestScrollTarget();
        if (heuristic) {
            console.log('[AI Assistant] findScrollTarget stage3 MATCH:', heuristic.description);
            return { kind: 'element', el: heuristic.el, description: heuristic.description };
        }
        console.log('[AI Assistant] findScrollTarget stage3: heuristic found nothing');

        // Stage 4: probe fallback — re-scan with relaxed overflow check
        //   Some apps use overflow:hidden + JS-driven scroll (custom scrollbars).
        //   Walk viewport-sampled elements looking for any with scrollHeight > clientHeight
        //   that respond to a scrollTop probe.
        var SAMPLE_POINTS_PROBE = [[0.5, 0.5], [0.5, 0.25], [0.5, 0.75]];
        var vpW = window.innerWidth;
        var vpH = window.innerHeight;
        var probed = new Set();

        for (var i = 0; i < SAMPLE_POINTS_PROBE.length; i++) {
            var x = Math.floor(vpW * SAMPLE_POINTS_PROBE[i][0]);
            var y = Math.floor(vpH * SAMPLE_POINTS_PROBE[i][1]);
            var el = document.elementFromPoint(x, y);
            while (el && el !== document.body) {
                if (!probed.has(el)) {
                    probed.add(el);
                    if (el.scrollHeight - el.clientHeight > SCROLLABLE_MIN_OVERFLOW) {
                        var rect = el.getBoundingClientRect();
                        if (rect.width >= SCROLLABLE_MIN_WIDTH && rect.height >= SCROLLABLE_MIN_HEIGHT) {
                            if (canScrollByProbe(el)) {
                                var tag = el.tagName.toLowerCase();
                                var id = el.id ? '#' + el.id : '';
                                console.log('[AI Assistant] findScrollTarget stage4 probe MATCH:', tag + id);
                                return {
                                    kind: 'element',
                                    el: el,
                                    description: 'probe:' + tag + id
                                };
                            }
                        }
                    }
                }
                el = el.parentElement;
            }
        }
        console.log('[AI Assistant] findScrollTarget stage4: probe found nothing');

        // Stage 5: last resort — check if window is technically scrollable even by small amount
        var scrollEl = document.scrollingElement || document.documentElement;
        if (scrollEl.scrollHeight > scrollEl.clientHeight + 1) {
            console.log('[AI Assistant] findScrollTarget stage5: window minimal scroll');
            return { kind: 'window', el: null, description: 'window:minimal' };
        }

        console.log('[AI Assistant] findScrollTarget: NO scroll target found');
        return { kind: 'none', el: null, description: 'no-scroll-target-found' };
    }

    // ==================== Capture Context Management ====================

    var captureContexts = {};
    var contextCounter = 0;

    function makeContextId() {
        contextCounter++;
        return 'ctx_' + Date.now() + '_' + contextCounter;
    }

    function getScrollTop(ctx) {
        if (ctx.kind === 'window') return window.scrollY;
        return ctx.el ? ctx.el.scrollTop : 0;
    }

    function getClientHeight(ctx) {
        if (ctx.kind === 'window') return window.innerHeight;
        return ctx.el ? ctx.el.clientHeight : window.innerHeight;
    }

    function getScrollHeight(ctx) {
        if (ctx.kind === 'window') {
            var se = document.scrollingElement || document.documentElement;
            return Math.max(se.scrollHeight, document.body ? document.body.scrollHeight : 0);
        }
        return ctx.el ? ctx.el.scrollHeight : 0;
    }

    function getClientWidth(ctx) {
        if (ctx.kind === 'window') return window.innerWidth;
        return ctx.el ? ctx.el.clientWidth : window.innerWidth;
    }

    function getScrollWidth(ctx) {
        if (ctx.kind === 'window') {
            var se = document.scrollingElement || document.documentElement;
            return Math.max(se.scrollWidth, document.body ? document.body.scrollWidth : 0);
        }
        return ctx.el ? ctx.el.scrollWidth : 0;
    }

    /**
     * Build context metrics object for the service worker.
     */
    function buildContextMetrics(ctx) {
        var scrollTop = getScrollTop(ctx);
        var scrollHeight = getScrollHeight(ctx);
        var clientHeight = getClientHeight(ctx);
        return {
            scrollTop: scrollTop,
            scrollHeight: scrollHeight,
            clientHeight: clientHeight,
            maxScrollTop: Math.max(0, scrollHeight - clientHeight),
            clientWidth: getClientWidth(ctx),
            scrollWidth: getScrollWidth(ctx)
        };
    }

    /**
     * Wait for scroll position to stabilize (handles lazy-rendering apps).
     * Checks via requestAnimationFrame — position must be stable for 2 consecutive frames.
     *
     * @param {function} readPos - Returns current scrollTop.
     * @param {number} timeoutMs - Maximum wait time (default 800ms).
     * @returns {Promise<number>} Settled scroll position.
     */
    function waitForScrollSettled(readPos, timeoutMs) {
        timeoutMs = timeoutMs || 800;
        return new Promise(function(resolve) {
            var start = performance.now();
            var last = readPos();

            function check() {
                if (performance.now() - start > timeoutMs) {
                    resolve(readPos());
                    return;
                }
                requestAnimationFrame(function() {
                    var now = readPos();
                    if (Math.abs(now - last) < 0.5) {
                        // Stable for 1 frame — confirm with another
                        requestAnimationFrame(function() {
                            var now2 = readPos();
                            if (Math.abs(now2 - now) < 0.5) {
                                resolve(now2);
                            } else {
                                last = now2;
                                check();
                            }
                        });
                    } else {
                        last = now;
                        check();
                    }
                });
            }

            check();
        });
    }

    /**
     * Initialize a capture context: detect scroll target, store it, return metrics.
     *
     * @param {Object} options - { forceRedetect: boolean }
     * @returns {Promise<Object>} Context initialization result.
     */
    function initCaptureContext(options) {
        options = options || {};

        var target = findScrollTarget();
        console.log('[AI Assistant] Scroll target detected:', target.kind, target.description);

        if (target.kind === 'none') {
            return Promise.resolve({
                ok: false,
                reason: 'NO_SCROLL_TARGET',
                debug: target.description
            });
        }

        var contextId = makeContextId();
        var ctx = {
            kind: target.kind,
            el: target.el,
            description: target.description
        };
        captureContexts[contextId] = ctx;

        var metrics = buildContextMetrics(ctx);
        var rectInViewport = null;
        if (target.kind === 'element' && target.el) {
            var r = target.el.getBoundingClientRect();
            rectInViewport = { left: r.left, top: r.top, width: r.width, height: r.height };
        }

        return Promise.resolve({
            ok: true,
            contextId: contextId,
            target: {
                kind: target.kind,
                description: target.description,
                rectInViewport: rectInViewport
            },
            metrics: metrics,
            page: {
                url: window.location.href,
                title: document.title,
                devicePixelRatio: window.devicePixelRatio || 1
            }
        });
    }

    /**
     * Scroll a capture context to a given Y position and wait for settle.
     *
     * @param {string} contextId
     * @param {number} top - Target scrollTop.
     * @returns {Promise<Object>} { ok, scrollTop }
     */
    function scrollContextTo(contextId, top) {
        var ctx = captureContexts[contextId];
        if (!ctx) {
            console.warn('[AI Assistant] scrollContextTo: INVALID contextId:', contextId, 'known:', Object.keys(captureContexts));
            return Promise.resolve({ ok: false, error: 'Invalid contextId' });
        }

        var safeTop = Math.max(0, Number.isFinite(top) ? top : 0);
        var before = getScrollTop(ctx);
        console.log('[AI Assistant] scrollContextTo:', contextId, 'kind:', ctx.kind, 'target:', top, 'safeTop:', safeTop, 'currentScrollTop:', before);

        if (ctx.kind === 'window') {
            window.scrollTo(0, safeTop);
        } else if (ctx.el) {
            ctx.el.scrollTop = safeTop;
        }

        return waitForScrollSettled(
            function() { return getScrollTop(ctx); },
            800
        ).then(function(settled) {
            console.log('[AI Assistant] scrollContextTo settled:', settled, '(target was:', safeTop, ')');
            return { ok: true, scrollTop: settled };
        });
    }

    /**
     * Re-read metrics for an existing context (useful for virtualized content).
     */
    function getContextMetrics(contextId) {
        var ctx = captureContexts[contextId];
        if (!ctx) {
            return { ok: false, error: 'Invalid contextId' };
        }
        return { ok: true, metrics: buildContextMetrics(ctx) };
    }

    /**
     * Release a capture context and clean up.
     */
    function releaseCaptureContext(contextId) {
        if (captureContexts[contextId]) {
            delete captureContexts[contextId];
            return { ok: true };
        }
        return { ok: false, error: 'Unknown contextId' };
    }

    // ==================== Quick Action API Call ====================

    /**
     * Make a quick action API request to the server.
     * This is the API-only part — no UI rendering. The UI layer
     * (extractor-ui.js) calls this and renders the result in a modal.
     *
     * @param {string} action - Action type (explain, summarize, critique, etc.)
     * @param {string} text - Text to process.
     * @returns {Promise<Object>} Server response JSON.
     */
    async function quickActionRequest(action, text) {
        const apiSettings = await chrome.storage.local.get('settings');
        const apiBaseUrl = (apiSettings.settings && apiSettings.settings.apiBaseUrl)
            ? apiSettings.settings.apiBaseUrl
            : 'http://localhost:5000';

        const response = await fetch(`${apiBaseUrl}/ext/chat/quick`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify({
                action,
                text,
                stream: false
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        return await response.json();
    }

    // ==================== Core Message Listener ====================

    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        // Only handle CORE message types; UI types handled by extractor-ui.js
        var CORE_TYPES = {
            'EXTRACT_PAGE': true,
            'GET_SELECTION': true,
            'GET_PAGE_METRICS': true,
            'SCROLL_TO': true,
            'INIT_CAPTURE_CONTEXT': true,
            'SCROLL_CONTEXT_TO': true,
            'GET_CONTEXT_METRICS': true,
            'RELEASE_CAPTURE_CONTEXT': true
        };

        if (!CORE_TYPES[message.type]) return; // not ours — let other listeners handle

        console.log('[AI Assistant] Core received:', message.type);

        try {
            switch (message.type) {
                case 'EXTRACT_PAGE':
                    const pageContent = extractPageContent();
                    console.log('[AI Assistant] Extracted content length:', pageContent.length);
                    sendResponse(pageContent);
                    break;

                case 'GET_SELECTION':
                    sendResponse(getSelectedText());
                    break;

                case 'GET_PAGE_METRICS':
                    sendResponse(getPageMetrics());
                    break;

                case 'SCROLL_TO':
                    sendResponse(scrollToPosition(message.y));
                    break;

                case 'INIT_CAPTURE_CONTEXT':
                    console.log('[AI Assistant] INIT_CAPTURE_CONTEXT start, url:', window.location.href);
                    initCaptureContext(message.options || {}).then(function(result) {
                        console.log('[AI Assistant] INIT_CAPTURE_CONTEXT result ok:', result.ok, 'kind:', result.target && result.target.kind, 'desc:', result.target && result.target.description);
                        sendResponse(result);
                    }).catch(function(err) {
                        console.error('[AI Assistant] INIT_CAPTURE_CONTEXT error:', err.message);
                        sendResponse({ ok: false, reason: 'INIT_ERROR', debug: err.message });
                    });
                    break;

                case 'SCROLL_CONTEXT_TO':
                    console.log('[AI Assistant] SCROLL_CONTEXT_TO contextId:', message.contextId, 'top:', message.top);
                    scrollContextTo(message.contextId, message.top).then(function(result) {
                        console.log('[AI Assistant] SCROLL_CONTEXT_TO done, scrollTop:', result.scrollTop);
                        sendResponse(result);
                    }).catch(function(err) {
                        console.error('[AI Assistant] SCROLL_CONTEXT_TO error:', err.message);
                        sendResponse({ ok: false, error: err.message });
                    });
                    break;

                case 'GET_CONTEXT_METRICS':
                    sendResponse(getContextMetrics(message.contextId));
                    break;

                case 'RELEASE_CAPTURE_CONTEXT':
                    sendResponse(releaseCaptureContext(message.contextId));
                    break;
            }
        } catch (error) {
            console.error('[AI Assistant] Core message handler error:', error);
            sendResponse({ error: error.message });
        }

        return true; // Keep channel open for async
    });

    // ==================== Public API Export ====================

    window.__extractorCore = {
        extractPageContent: extractPageContent,
        getSelectedText: getSelectedText,
        getPageMetrics: getPageMetrics,
        scrollToPosition: scrollToPosition,
        quickActionRequest: quickActionRequest,
        initCaptureContext: initCaptureContext,
        scrollContextTo: scrollContextTo,
        getContextMetrics: getContextMetrics,
        releaseCaptureContext: releaseCaptureContext,
        findScrollTarget: findScrollTarget
    };

    console.log('[AI Assistant] Extractor core ready');
})();
