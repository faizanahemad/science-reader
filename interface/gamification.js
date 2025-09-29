
// ============= GAMIFICATION SYSTEM =============

/**
 * Audio files mapping for gamification system
 */
const GAMIFICATION_AUDIO = {
    // Reward sounds
    'reward_excellent': '/static/audio/reward_excellent.wav',
    'reward_very_good': '/static/audio/reward_very_good.wav', 
    'reward_good': '/static/audio/reward_good.wav',
    'reward_fair': '/static/audio/reward_fair.wav',
    'reward_basic': '/static/audio/reward_basic.wav',
    
    // Penalty sounds
    'penalty_minor': '/static/audio/penalty_minor.wav',
    'penalty_moderate': '/static/audio/penalty_moderate.wav',
    'penalty_significant': '/static/audio/penalty_significant.wav',
    'penalty_major': '/static/audio/penalty_major.wav',
    'penalty_critical': '/static/audio/penalty_critical.wav'
};

/**
 * Animation CSS classes for gamification system (Enhanced Duolingo-style)
 */
const GAMIFICATION_ANIMATIONS = {
    // Celebration animations - More flashy and modern
    'celebration_5': 'animate__animated animate__bounceIn animate__slow celebration-gold flashy-celebration trophy-celebration',
    'celebration_4': 'animate__animated animate__zoomIn animate__slow celebration-silver flashy-celebration star-celebration',
    'celebration_3': 'animate__animated animate__jackInTheBox animate__slow celebration-bronze flashy-celebration medal-celebration',
    'celebration_2': 'animate__animated animate__heartBeat animate__repeat-2 celebration-good flashy-celebration thumbs-celebration',
    'celebration_1': 'animate__animated animate__bounceInUp celebration-basic flashy-celebration check-celebration',
    
    // Disappointment animations - More dramatic and expressive
    'disappointment_5': 'animate__animated animate__shakeX animate__repeat-3 disappointment-critical flashy-penalty explosion-penalty',
    'disappointment_4': 'animate__animated animate__headShake animate__repeat-2 disappointment-major flashy-penalty warning-penalty',
    'disappointment_3': 'animate__animated animate__wobble animate__repeat-2 disappointment-significant flashy-penalty frown-penalty',
    'disappointment_2': 'animate__animated animate__swing disappointment-moderate flashy-penalty meh-penalty',
    'disappointment_1': 'animate__animated animate__fadeInDown disappointment-minor flashy-penalty info-penalty'
};

/**
 * Play audio for gamification feedback
 * @param {string} audioName - Name of the audio file to play
 */
function playGamificationAudio(audioName) {
    try {
        const audioPath = GAMIFICATION_AUDIO[audioName];
        if (!audioPath) {
            console.warn('Audio not found:', audioName);
            return;
        }

        // Create audio element
        const audio = new Audio(audioPath);
        audio.volume = 0.6; // Set moderate volume
        
        // Play with error handling
        const playPromise = audio.play();
        if (playPromise !== undefined) {
            playPromise.catch(error => {
                console.warn('Audio playback failed:', error);
                // Fallback: try to play a generic notification sound
                try {
                    const fallbackAudio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+DyvmUgBjeH0fPTgyoFJmq+8OONOggWZpjh8K2AXAL4');
                    fallbackAudio.volume = 0.3;
                    fallbackAudio.play();
                } catch (fallbackError) {
                    console.warn('Fallback audio also failed:', fallbackError);
                }
            });
        }
        
        // Clean up audio element after playing
        audio.addEventListener('ended', () => {
            audio.remove();
        });
        
    } catch (error) {
        console.error('Error playing gamification audio:', error);
    }
}

/**
 * Show enhanced gamification animation with message support (Duolingo-style)
 * @param {string} animationName - Name of the animation to show
 * @param {jQuery} targetCard - Card element to animate (optional)
 * @param {string} message - Optional message to display below animation
 */
function showGamificationAnimation(animationName, targetCard = null, message = '') {
    try {
        const animationClasses = GAMIFICATION_ANIMATIONS[animationName];
        if (!animationClasses) {
            console.warn('Animation not found:', animationName);
            return;
        }

        // Create enhanced floating animation element with message support
        const animationElement = $(`
            <div class="gamification-animation-overlay modern-overlay">
                <div class="gamification-animation-content ${animationClasses}">
                    <div class="animation-main-content">
                        ${getAnimationIcon(animationName)}
                    </div>
                    ${message ? `
                        <div class="animation-message">
                            <div class="message-text">${message}</div>
                        </div>
                    ` : ''}
                </div>
                <div class="background-particles"></div>
                <div class="glow-effect"></div>
            </div>
        `);

        // Position the animation
        let targetElement = targetCard || $('.chat-container').last();
        if (targetElement.length === 0) {
            targetElement = $('body');
        }

        // Append to target
        targetElement.append(animationElement);

        // Position animation overlay
        animationElement.css({
            position: 'fixed',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            zIndex: 9999,
            pointerEvents: 'none'
        });

        // Add enhanced effects based on animation type and level
        const level = parseInt(animationName.split('_')[1]) || 1;
        
        if (animationName.includes('celebration')) {
            createParticleEffect(animationElement, 'celebration');
            createFlagEffect(animationElement, 'green', level);
            createPartyPopperEffect(animationElement, level);
            if (level >= 4) {
                createConfettiRain(animationElement, level);
            }
        } else if (animationName.includes('disappointment')) {
            createParticleEffect(animationElement, 'disappointment');
            createFlagEffect(animationElement, 'red', level);
            createExplosionEffect(animationElement, level);
            if (level >= 3) {
                createFlameEffect(animationElement, level);
            }
        }

        // Enhanced removal with staggered fadeout (Extended duration)
        setTimeout(() => {
            animationElement.find('.background-particles').fadeOut(800);
            setTimeout(() => {
                animationElement.find('.animation-message').fadeOut(600);
                setTimeout(() => {
                    animationElement.find('.animation-main-content').fadeOut(400, function() {
                        animationElement.remove();
                    });
                }, 300);
            }, 200);
        }, 4000); // Show for 4 seconds (extended from 2)

    } catch (error) {
        console.error('Error showing gamification animation:', error);
    }
}

/**
 * Create particle effects for animations
 * @param {jQuery} container - Animation container
 * @param {string} type - Effect type ('celebration' or 'disappointment')
 */
function createParticleEffect(container, type) {
    try {
        const particleCount = type === 'celebration' ? 20 : 10;
        const particles = container.find('.background-particles');
        
        for (let i = 0; i < particleCount; i++) {
            const particle = $(`<div class="particle particle-${type}"></div>`);
            particles.append(particle);
            
            // Random positioning and animation
            const delay = Math.random() * 2000;
            const duration = 1000 + Math.random() * 2000;
            const startX = Math.random() * 100;
            const startY = Math.random() * 100;
            const endX = startX + (Math.random() - 0.5) * 200;
            const endY = startY + (Math.random() - 0.5) * 200;
            
            particle.css({
                left: `${startX}%`,
                top: `${startY}%`,
                animationDelay: `${delay}ms`,
                animationDuration: `${duration}ms`
            });
            
            // Animate particle movement
            setTimeout(() => {
                particle.animate({
                    left: `${endX}%`,
                    top: `${endY}%`,
                    opacity: 0
                }, duration);
            }, delay);
        }
    } catch (error) {
        console.error('Error creating particle effect:', error);
    }
}

/**
 * Create flag effects floating from sides
 * @param {jQuery} container - Animation container
 * @param {string} color - Flag color ('green' or 'red')
 * @param {number} level - Intensity level (1-5)
 */
function createFlagEffect(container, color, level) {
    try {
        const flagCount = level * 2; // 2-10 flags based on level
        const particles = container.find('.background-particles');
        
        for (let i = 0; i < flagCount; i++) {
            const isLeftSide = Math.random() > 0.5;
            const flag = $(`<div class="flag flag-${color}">🚩</div>`);
            particles.append(flag);
            
            const delay = Math.random() * 1000 + i * 100;
            const duration = 2000 + Math.random() * 1000;
            const startY = 20 + Math.random() * 60; // Random height
            const startX = isLeftSide ? -50 : 150;
            const endX = isLeftSide ? 120 : -30;
            
            flag.css({
                position: 'absolute',
                left: `${startX}%`,
                top: `${startY}%`,
                fontSize: `${0.8 + level * 0.2}rem`,
                zIndex: 10,
                filter: color === 'green' ? 'hue-rotate(60deg)' : 'hue-rotate(320deg)',
                animationDelay: `${delay}ms`
            });
            
            // Animate flag movement
            setTimeout(() => {
                flag.animate({
                    left: `${endX}%`,
                    top: `${startY - 10}%`,
                    opacity: 0
                }, duration, 'easeOutQuad');
            }, delay);
        }
    } catch (error) {
        console.error('Error creating flag effect:', error);
    }
}

/**
 * Create party popper effects for celebrations
 * @param {jQuery} container - Animation container  
 * @param {number} level - Intensity level (1-5)
 */
function createPartyPopperEffect(container, level) {
    try {
        const popperCount = Math.min(level, 3); // Max 3 poppers
        const particles = container.find('.background-particles');
        
        for (let i = 0; i < popperCount; i++) {
            const popper = $(`<div class="party-popper">🎉</div>`);
            particles.append(popper);
            
            const delay = i * 300;
            const startX = 20 + i * 30;
            const startY = 80;
            
            popper.css({
                position: 'absolute',
                left: `${startX}%`,
                top: `${startY}%`,
                fontSize: '2rem',
                zIndex: 15,
                animation: `popperPop 0.8s ease-out ${delay}ms`
            });
            
            // Create popper explosion
            setTimeout(() => {
                createPopperExplosion(particles, startX, startY - 20, level);
            }, delay + 200);
        }
    } catch (error) {
        console.error('Error creating party popper effect:', error);
    }
}

/**
 * Create popper explosion with streamers
 */
function createPopperExplosion(container, x, y, level) {
    const streamers = ['🎊', '✨', '🌟', '💫', '⭐'];
    const streamerCount = level * 3;
    
    for (let i = 0; i < streamerCount; i++) {
        const streamer = $(`<div class="streamer">${streamers[Math.floor(Math.random() * streamers.length)]}</div>`);
        container.append(streamer);
        
        const angle = (Math.PI * 2 * i) / streamerCount;
        const distance = 50 + Math.random() * 100;
        const endX = x + Math.cos(angle) * distance;
        const endY = y + Math.sin(angle) * distance;
        
        streamer.css({
            position: 'absolute',
            left: `${x}%`,
            top: `${y}%`,
            fontSize: '1rem',
            zIndex: 12
        });
        
        streamer.animate({
            left: `${endX}%`,
            top: `${endY}%`,
            opacity: 0
        }, 1500 + Math.random() * 500);
    }
}

/**
 * Create confetti rain for high-level celebrations
 * @param {jQuery} container - Animation container
 * @param {number} level - Intensity level (4-5 for confetti)
 */
function createConfettiRain(container, level) {
    try {
        const confettiCount = level * 8; // More confetti for higher levels
        const particles = container.find('.background-particles');
        const confettiColors = ['🟥', '🟩', '🟦', '🟨', '🟪', '🟧'];
        
        for (let i = 0; i < confettiCount; i++) {
            const confetti = $(`<div class="confetti">${confettiColors[Math.floor(Math.random() * confettiColors.length)]}</div>`);
            particles.append(confetti);
            
            const delay = Math.random() * 1000;
            const startX = Math.random() * 120 - 10;
            const duration = 2000 + Math.random() * 1000;
            
            confetti.css({
                position: 'absolute',
                left: `${startX}%`,
                top: '-10%',
                fontSize: '0.8rem',
                zIndex: 8,
                animation: `confettiFall ${duration}ms linear ${delay}ms`
            });
        }
    } catch (error) {
        console.error('Error creating confetti rain:', error);
    }
}

/**
 * Create explosion effects for penalties
 * @param {jQuery} container - Animation container
 * @param {number} level - Intensity level (1-5)
 */
function createExplosionEffect(container, level) {
    try {
        const explosionCount = Math.min(level, 4); // Max 4 explosions
        const particles = container.find('.background-particles');
        const explosionEmojis = ['💥', '💢', '⚡', '💀'];
        
        for (let i = 0; i < explosionCount; i++) {
            const explosion = $(`<div class="explosion">${explosionEmojis[i % explosionEmojis.length]}</div>`);
            particles.append(explosion);
            
            const delay = i * 200;
            const x = 30 + Math.random() * 40;
            const y = 30 + Math.random() * 40;
            
            explosion.css({
                position: 'absolute',
                left: `${x}%`,
                top: `${y}%`,
                fontSize: `${1.5 + level * 0.3}rem`,
                zIndex: 15,
                animation: `explosionBlast 0.6s ease-out ${delay}ms`
            });
            
            // Create explosion shockwave
            setTimeout(() => {
                createShockwave(particles, x, y, level);
            }, delay + 100);
        }
    } catch (error) {
        console.error('Error creating explosion effect:', error);
    }
}

/**
 * Create shockwave effect for explosions
 */
function createShockwave(container, x, y, level) {
    const shockwave = $(`<div class="shockwave"></div>`);
    container.append(shockwave);
    
    shockwave.css({
        position: 'absolute',
        left: `${x}%`,
        top: `${y}%`,
        width: '20px',
        height: '20px',
        border: `2px solid rgba(255, 0, 0, 0.8)`,
        borderRadius: '50%',
        zIndex: 10,
        animation: `shockwaveExpand 0.8s ease-out`
    });
}

/**
 * Create flame effects for high-level penalties (Mario-style)
 * @param {jQuery} container - Animation container
 * @param {number} level - Intensity level (3-5 for flames)
 */
function createFlameEffect(container, level) {
    try {
        const flameCount = (level - 2) * 2; // 2-6 flames for levels 3-5
        const particles = container.find('.background-particles');
        const flameEmojis = ['🔥', '🌋', '💢'];
        
        for (let i = 0; i < flameCount; i++) {
            const flame = $(`<div class="flame">${flameEmojis[Math.floor(Math.random() * flameEmojis.length)]}</div>`);
            particles.append(flame);
            
            const delay = Math.random() * 800;
            const startX = Math.random() * 80 + 10;
            const startY = 90 + Math.random() * 10;
            const endY = startY - 60 - Math.random() * 30;
            
            flame.css({
                position: 'absolute',
                left: `${startX}%`,
                top: `${startY}%`,
                fontSize: `${1 + level * 0.2}rem`,
                zIndex: 12,
                animation: `flameRise ${1500 + Math.random() * 500}ms ease-out ${delay}ms`
            });
        }
    } catch (error) {
        console.error('Error creating flame effect:', error);
    }
}

/**
 * Get appropriate icon and emoji for animation type (Enhanced with more expressive emojis)
 * @param {string} animationName - Name of animation
 * @returns {string} HTML for icon with emoji
 */
function getAnimationIcon(animationName) {
    if (animationName.includes('celebration')) {
        const level = animationName.split('_')[1];
        switch(level) {
            case '5': return `
                <div class="icon-combo">
                    <div class="main-emoji">🏆</div>
                    <div class="sparkle-effects">✨🎉✨</div>
                    <div class="sub-text">EXCELLENT!</div>
                </div>`;
            case '4': return `
                <div class="icon-combo">
                    <div class="main-emoji">🌟</div>
                    <div class="sparkle-effects">⭐🎊⭐</div>
                    <div class="sub-text">VERY GOOD!</div>
                </div>`;
            case '3': return `
                <div class="icon-combo">
                    <div class="main-emoji">🎉</div>
                    <div class="sparkle-effects">🎈🎀🎈</div>
                    <div class="sub-text">GOOD!</div>
                </div>`;
            case '2': return `
                <div class="icon-combo">
                    <div class="main-emoji">👍</div>
                    <div class="sparkle-effects">😊💪😊</div>
                    <div class="sub-text">FAIR!</div>
                </div>`;
            case '1': return `
                <div class="icon-combo">
                    <div class="main-emoji">✅</div>
                    <div class="sparkle-effects">🙂👌🙂</div>
                    <div class="sub-text">BASIC!</div>
                </div>`;
            default: return `
                <div class="icon-combo">
                    <div class="main-emoji">😊</div>
                    <div class="sub-text">GOOD!</div>
                </div>`;
        }
    } else if (animationName.includes('disappointment')) {
        const level = animationName.split('_')[1];
        switch(level) {
            case '5': return `
                <div class="icon-combo">
                    <div class="main-emoji">💥</div>
                    <div class="sparkle-effects">😤🤬😤</div>
                    <div class="sub-text">CRITICAL!</div>
                </div>`;
            case '4': return `
                <div class="icon-combo">
                    <div class="main-emoji">😨</div>
                    <div class="sparkle-effects">😠⚠️😠</div>
                    <div class="sub-text">MAJOR!</div>
                </div>`;
            case '3': return `
                <div class="icon-combo">
                    <div class="main-emoji">😞</div>
                    <div class="sparkle-effects">🤦‍♂️😕🤦‍♀️</div>
                    <div class="sub-text">SIGNIFICANT!</div>
                </div>`;
            case '2': return `
                <div class="icon-combo">
                    <div class="main-emoji">😕</div>
                    <div class="sparkle-effects">😐🤷‍♂️😐</div>
                    <div class="sub-text">MODERATE!</div>
                </div>`;
            case '1': return `
                <div class="icon-combo">
                    <div class="main-emoji">⚠️</div>
                    <div class="sparkle-effects">😬💭😬</div>
                    <div class="sub-text">MINOR!</div>
                </div>`;
            default: return `
                <div class="icon-combo">
                    <div class="main-emoji">❓</div>
                    <div class="sub-text">UNKNOWN</div>
                </div>`;
        }
    }
    return '<div class="icon-combo"><div class="main-emoji">🔔</div></div>';
}

/**
 * Parse and handle gamification tags in streaming text (Enhanced with message support)
 * @param {string} text - Text chunk to parse
 * @param {jQuery} targetCard - Card element for animations
 * @returns {string} Text with gamification tags removed
 */
function parseGamificationTags(text, targetCard = null) {
    let processedText = text;
    let pendingMessage = '';
    
    try {
        // Handle message tags first to capture message for animation
        const messageMatches = text.match(/<message[^>]*>([^<]+)<\/message>/g);
        if (messageMatches) {
            messageMatches.forEach(match => {
                pendingMessage = match.replace(/<message[^>]*>|<\/message>/g, '');
                processedText = processedText.replace(match, '');
            });
        }

        // Handle audio tags - UPDATED to handle attributes
        const audioMatches = text.match(/<audio[^>]*>([^<]+)<\/audio>/g);
        if (audioMatches) {
            audioMatches.forEach(match => {
                const audioName = match.replace(/<audio[^>]*>|<\/audio>/g, '');
                playGamificationAudio(audioName);
                processedText = processedText.replace(match, '');
            });
        }

        // Handle animation tags - UPDATED to handle attributes and message support
        const animationMatches = text.match(/<animation[^>]*>([^<]+)<\/animation>/g);
        if (animationMatches) {
            animationMatches.forEach(match => {
                const animationName = match.replace(/<animation[^>]*>|<\/animation>/g, '');
                // Pass the pending message to the animation
                showGamificationAnimation(animationName, targetCard, pendingMessage);
                processedText = processedText.replace(match, '');
                // Clear the pending message after use
                pendingMessage = '';
            });
        }
        
    } catch (error) {
        console.error('Error parsing gamification tags:', error);
    }
    
    return processedText;
}

/**
 * Initialize gamification system (load animate.css if not present)
 */
function initializeGamificationSystem() {
    // Check if animate.css is loaded
    if (!$('link[href*="animate.css"]').length) {
        // Load animate.css from CDN
        $('<link>')
            .attr('rel', 'stylesheet')
            .attr('href', 'https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css')
            .appendTo('head');
    }
    
    // Add enhanced custom CSS for modern gamification animations (Duolingo-style)
    if (!$('#gamification-styles').length) {
        $(`<style id="gamification-styles">
            .gamification-animation-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                pointer-events: none;
                z-index: 9999;
                display: flex;
                align-items: center;
                justify-content: center;
                backdrop-filter: blur(3px);
            }
            
            .modern-overlay {
                background: radial-gradient(circle at center, rgba(0,0,0,0.1) 0%, rgba(0,0,0,0.05) 100%);
            }
            
            .gamification-animation-content {
                position: relative;
                padding: 30px;
                border-radius: 20px;
                background: rgba(255, 255, 255, 0.98);
                box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3), 0 8px 20px rgba(0, 0, 0, 0.2);
                text-align: center;
                border: 3px solid rgba(255, 255, 255, 0.8);
                backdrop-filter: blur(10px);
                max-width: 400px;
                min-height: 200px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
            }
            
            .animation-main-content {
                margin-bottom: 15px;
            }
            
            .animation-message {
                margin-top: 15px;
                padding: 15px;
                background: rgba(0, 0, 0, 0.05);
                border-radius: 12px;
                border-left: 4px solid currentColor;
                max-width: 300px;
            }
            
            .message-text {
                font-size: 16px;
                font-weight: 500;
                line-height: 1.4;
                color: inherit;
            }
            
            .icon-combo {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 10px;
            }
            
            .main-emoji {
                font-size: 4rem;
                line-height: 1;
                text-shadow: 0 0 20px rgba(0,0,0,0.2);
                animation: mainEmojiPulse 2s ease-in-out infinite;
            }
            
            .sparkle-effects {
                font-size: 1.5rem;
                animation: sparkleRotate 3s linear infinite;
                margin: 5px 0;
            }
            
            .sub-text {
                font-size: 1.2rem;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 2px;
                margin-top: 5px;
                animation: subTextBounce 2s ease-in-out infinite;
            }
            
            .background-particles {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                pointer-events: none;
                overflow: hidden;
                border-radius: 20px;
            }
            
            .particle {
                position: absolute;
                border-radius: 50%;
                pointer-events: none;
            }
            
            .particle-celebration {
                background: radial-gradient(circle, #ffd700, #ff6b35);
                width: 8px;
                height: 8px;
                animation: celebrationFloat 3s ease-out infinite;
            }
            
            .particle-disappointment {
                background: radial-gradient(circle, #dc3545, #6c757d);
                width: 6px;
                height: 6px;
                animation: disappointmentSink 2s ease-in infinite;
            }
            
            .glow-effect {
                position: absolute;
                top: -10px;
                left: -10px;
                right: -10px;
                bottom: -10px;
                border-radius: 25px;
                opacity: 0.5;
                animation: glowPulse 2s ease-in-out infinite;
            }
            
            /* Enhanced color schemes with more vibrant gradients */
            .celebration-gold { 
                background: linear-gradient(135deg, #ffd700 0%, #ffed4e 50%, #ffa500 100%);
                color: #b8860b;
                border-color: #ffd700;
            }
            
            .celebration-gold .glow-effect {
                background: linear-gradient(135deg, #ffd700, #ffa500);
            }
            
            .celebration-silver { 
                background: linear-gradient(135deg, #e6e6fa 0%, #d3d3d3 50%, #b0c4de 100%);
                color: #696969;
                border-color: #c0c0c0;
            }
            
            .celebration-silver .glow-effect {
                background: linear-gradient(135deg, #e6e6fa, #b0c4de);
            }
            
            .celebration-bronze { 
                background: linear-gradient(135deg, #cd7f32 0%, #daa520 50%, #b8860b 100%);
                color: #8b4513;
                border-color: #cd7f32;
            }
            
            .celebration-bronze .glow-effect {
                background: linear-gradient(135deg, #cd7f32, #b8860b);
            }
            
            .celebration-good { 
                background: linear-gradient(135deg, #28a745 0%, #6fd64f 50%, #20c997 100%);
                color: white;
                border-color: #28a745;
            }
            
            .celebration-good .glow-effect {
                background: linear-gradient(135deg, #28a745, #20c997);
            }
            
            .celebration-basic { 
                background: linear-gradient(135deg, #17a2b8 0%, #5bc0de 50%, #6f42c1 100%);
                color: white;
                border-color: #17a2b8;
            }
            
            .celebration-basic .glow-effect {
                background: linear-gradient(135deg, #17a2b8, #6f42c1);
            }
            
            .disappointment-critical { 
                background: linear-gradient(135deg, #dc3545 0%, #ff6b7a 50%, #e74c3c 100%);
                color: white;
                border-color: #dc3545;
            }
            
            .disappointment-critical .glow-effect {
                background: linear-gradient(135deg, #dc3545, #e74c3c);
            }
            
            .disappointment-major { 
                background: linear-gradient(135deg, #fd7e14 0%, #ffa726 50%, #ff8c00 100%);
                color: white;
                border-color: #fd7e14;
            }
            
            .disappointment-major .glow-effect {
                background: linear-gradient(135deg, #fd7e14, #ff8c00);
            }
            
            .disappointment-significant { 
                background: linear-gradient(135deg, #ffc107 0%, #ffeb3b 50%, #f39c12 100%);
                color: #856404;
                border-color: #ffc107;
            }
            
            .disappointment-significant .glow-effect {
                background: linear-gradient(135deg, #ffc107, #f39c12);
            }
            
            .disappointment-moderate { 
                background: linear-gradient(135deg, #6c757d 0%, #adb5bd 50%, #95a5a6 100%);
                color: white;
                border-color: #6c757d;
            }
            
            .disappointment-moderate .glow-effect {
                background: linear-gradient(135deg, #6c757d, #95a5a6);
            }
            
            .disappointment-minor { 
                background: linear-gradient(135deg, #6f9bd8 0%, #8bb8e8 50%, #3498db 100%);
                color: white;
                border-color: #6f9bd8;
            }
            
            .disappointment-minor .glow-effect {
                background: linear-gradient(135deg, #6f9bd8, #3498db);
            }
            
            /* Modern animations */
            @keyframes mainEmojiPulse {
                0%, 100% { transform: scale(1); }
                50% { transform: scale(1.1); }
            }
            
            @keyframes sparkleRotate {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            @keyframes subTextBounce {
                0%, 100% { transform: translateY(0); }
                50% { transform: translateY(-5px); }
            }
            
            @keyframes celebrationFloat {
                0% { transform: translateY(0) rotate(0deg); opacity: 1; }
                100% { transform: translateY(-100px) rotate(360deg); opacity: 0; }
            }
            
            @keyframes disappointmentSink {
                0% { transform: translateY(0) rotate(0deg); opacity: 1; }
                100% { transform: translateY(50px) rotate(-180deg); opacity: 0; }
            }
            
            @keyframes glowPulse {
                0%, 100% { opacity: 0.3; transform: scale(0.98); }
                50% { opacity: 0.6; transform: scale(1.02); }
            }
            
            /* Flashy celebration effects */
            .flashy-celebration {
                animation: flashyCelebrate 1s ease-in-out;
            }
            
            .flashy-penalty {
                animation: flashyPenalty 1s ease-in-out;
            }
            
            @keyframes flashyCelebrate {
                0% { transform: scale(0.5) rotate(-180deg); opacity: 0; }
                50% { transform: scale(1.2) rotate(0deg); opacity: 1; }
                100% { transform: scale(1) rotate(0deg); opacity: 1; }
            }
            
            @keyframes flashyPenalty {
                0% { transform: scale(0.8); opacity: 0; }
                25% { transform: scale(1.1) rotate(-5deg); opacity: 1; }
                50% { transform: scale(0.9) rotate(5deg); opacity: 1; }
                75% { transform: scale(1.05) rotate(-2deg); opacity: 1; }
                100% { transform: scale(1) rotate(0deg); opacity: 1; }
            }
            
            /* Enhanced effect animations */
            @keyframes popperPop {
                0% { transform: scale(0.5) rotate(0deg); opacity: 0; }
                50% { transform: scale(1.3) rotate(180deg); opacity: 1; }
                100% { transform: scale(1) rotate(360deg); opacity: 0; }
            }
            
            @keyframes confettiFall {
                0% { transform: translateY(0) rotate(0deg); opacity: 1; }
                100% { transform: translateY(400px) rotate(720deg); opacity: 0; }
            }
            
            @keyframes explosionBlast {
                0% { transform: scale(0.3) rotate(0deg); opacity: 1; filter: brightness(2); }
                50% { transform: scale(1.5) rotate(180deg); opacity: 1; filter: brightness(3) contrast(2); }
                100% { transform: scale(2) rotate(360deg); opacity: 0; filter: brightness(1); }
            }
            
            @keyframes shockwaveExpand {
                0% { transform: scale(0); opacity: 1; border-width: 3px; }
                50% { opacity: 0.8; border-width: 2px; }
                100% { transform: scale(5); opacity: 0; border-width: 1px; }
            }
            
            @keyframes flameRise {
                0% { transform: translateY(0) scale(0.8); opacity: 1; }
                25% { transform: translateY(-20px) scale(1.1); opacity: 0.9; }
                50% { transform: translateY(-40px) scale(1); opacity: 0.7; }
                75% { transform: translateY(-60px) scale(1.2); opacity: 0.5; }
                100% { transform: translateY(-80px) scale(0.8); opacity: 0; }
            }
            
            /* Flag specific styles */
            .flag {
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                animation: flagWave 0.5s ease-in-out infinite alternate;
            }
            
            @keyframes flagWave {
                0% { transform: rotate(-5deg) scale(1); }
                100% { transform: rotate(5deg) scale(1.1); }
            }
            
            .flag-green {
                filter: hue-rotate(60deg) brightness(1.2) saturate(1.5);
            }
            
            .flag-red {
                filter: hue-rotate(320deg) brightness(1.2) saturate(1.5);
            }
            
            /* Party popper and streamer styles */
            .party-popper {
                text-shadow: 0 0 10px rgba(255, 215, 0, 0.8);
            }
            
            .streamer {
                animation: streamerSpin 1.5s ease-out;
            }
            
            @keyframes streamerSpin {
                0% { transform: scale(0.5) rotate(0deg); }
                50% { transform: scale(1.2) rotate(180deg); }
                100% { transform: scale(0.8) rotate(360deg); }
            }
            
            /* Explosion and flame styles */
            .explosion {
                text-shadow: 0 0 15px rgba(255, 0, 0, 0.8);
                filter: brightness(1.5) contrast(1.3);
            }
            
            .flame {
                text-shadow: 0 0 10px rgba(255, 69, 0, 0.9);
                filter: brightness(1.3) contrast(1.2) hue-rotate(10deg);
                animation: flameFlicker 0.3s ease-in-out infinite alternate;
            }
            
            @keyframes flameFlicker {
                0% { filter: brightness(1.3) contrast(1.2) hue-rotate(10deg); }
                100% { filter: brightness(1.6) contrast(1.4) hue-rotate(-10deg); }
            }
            
            /* Confetti styles */
            .confetti {
                text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
            }
        </style>`).appendTo('head');
    }
}



// ============= END GAMIFICATION SYSTEM =============
