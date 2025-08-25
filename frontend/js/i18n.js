/**
 * YT Ultra HD - Internationalization
 * Multi-language support with real-time backend integration
 */

class I18nManager {
    constructor() {
        this.currentLanguage = 'en';
        this.fallbackLanguage = 'en';
        this.translations = new Map();
        this.rtlLanguages = ['ar', 'he', 'fa', 'ur'];
        this.loadedLanguages = new Set();
        this.observers = new Set();

        this.init();
    }

    init() {
        console.log('🌐 I18n Manager initialized');
        this.detectLanguage();
        this.setupLanguageObserver();
        this.loadDefaultTranslations();
        this.updatePageDirection();
        this.setupLanguageSelector();
    }

    // Language detection
    detectLanguage() {
        // Check URL parameter first
        const urlParams = new URLSearchParams(window.location.search);
        const urlLang = urlParams.get('lang');

        if (urlLang && this.isValidLanguage(urlLang)) {
            this.currentLanguage = urlLang;
            this.saveLanguagePreference(urlLang);
            return;
        }

        // Check saved preference
        const savedLang = localStorage.getItem('yt-language');
        if (savedLang && this.isValidLanguage(savedLang)) {
            this.currentLanguage = savedLang;
            return;
        }

        // Check browser language
        const browserLang = navigator.language || navigator.languages?.[0];
        if (browserLang) {
            const lang = browserLang.split('-')[0];
            if (this.isValidLanguage(lang)) {
                this.currentLanguage = lang;
                this.saveLanguagePreference(lang);
                return;
            }
        }

        // Default to English
        this.currentLanguage = this.fallbackLanguage;
        console.log(`🌐 Language detected: ${this.currentLanguage}`);
    }

    // Supported languages
    getSupportedLanguages() {
        return {
            'en': { name: 'English', nativeName: 'English', flag: '🇺🇸' },
            'es': { name: 'Spanish', nativeName: 'Español', flag: '🇪🇸' },
            'fr': { name: 'French', nativeName: 'Français', flag: '🇫🇷' },
            'de': { name: 'German', nativeName: 'Deutsch', flag: '🇩🇪' },
            'it': { name: 'Italian', nativeName: 'Italiano', flag: '🇮🇹' },
            'pt': { name: 'Portuguese', nativeName: 'Português', flag: '🇵🇹' },
            'ru': { name: 'Russian', nativeName: 'Русский', flag: '🇷🇺' },
            'zh': { name: 'Chinese', nativeName: '中文', flag: '🇨🇳' },
            'ja': { name: 'Japanese', nativeName: '日本語', flag: '🇯🇵' },
            'ko': { name: 'Korean', nativeName: '한국어', flag: '🇰🇷' },
            'ar': { name: 'Arabic', nativeName: 'العربية', flag: '🇸🇦' },
            'hi': { name: 'Hindi', nativeName: 'हिन्दी', flag: '🇮🇳' },
            'tr': { name: 'Turkish', nativeName: 'Türkçe', flag: '🇹🇷' },
            'nl': { name: 'Dutch', nativeName: 'Nederlands', flag: '🇳🇱' },
            'pl': { name: 'Polish', nativeName: 'Polski', flag: '🇵🇱' }
        };
    }

    isValidLanguage(lang) {
        return this.getSupportedLanguages().hasOwnProperty(lang);
    }

    // Load default translations (English)
    loadDefaultTranslations() {
        const defaultTranslations = {
            // Navigation
            'nav.home': 'Home',
            'nav.download': 'Download',
            'nav.4k-videos': '4K Videos',
            'nav.about': 'About',
            'nav.contact': 'Contact',

            // Hero section
            'hero.title': 'Download YouTube Videos in Ultra HD 4K',
            'hero.subtitle': 'Free, fast, and unlimited YouTube video downloader. Download videos in 4K, HD, or extract audio in MP3 format. No registration required.',
            'hero.url.placeholder': 'Paste YouTube URL here...',
            'hero.analyze.button': 'Analyze Video',
            'hero.analyze.loading': 'Analyzing...',
            'hero.supports.text': 'Supports all YouTube video formats and playlists',

            // Video info
            'video.duration': 'Duration',
            'video.views': 'views',
            'video.uploader': 'Uploader',
            'video.upload_date': 'Upload Date',
            'video.quality.select': 'Select Quality & Format:',
            'video.download.button': 'Download Video',
            'video.download.audio': 'Download Audio (MP3)',
            'video.share.button': 'Share',

            // Quality options
            'quality.best': 'Best Quality',
            'quality.4k': '4K Ultra HD',
            'quality.1080p': 'Full HD 1080p',
            'quality.720p': 'HD 720p',
            'quality.480p': 'SD 480p',
            'quality.audio': 'MP3 Audio',

            // Download progress
            'download.progress': 'Download Progress',
            'download.starting': 'Starting download...',
            'download.downloading': 'Downloading...',
            'download.finalizing': 'Finalizing...',
            'download.completed': 'Download Complete!',
            'download.failed': 'Download Failed',
            'download.speed': 'Speed',
            'download.eta': 'ETA',
            'download.elapsed': 'Elapsed',
            'download.downloaded': 'Downloaded',
            'download.another': 'Download Another',
            'download.retry': 'Retry Download',

            // Status messages
            'status.waiting': 'Waiting',
            'status.processing': 'Processing',
            'status.downloading': 'Downloading',
            'status.completed': 'Completed',
            'status.error': 'Error',

            // Features
            'features.title': 'Why Choose YT Ultra HD?',
            'features.subtitle': 'The most powerful YouTube downloader with cutting-edge features',
            'features.fast.title': 'Ultra-Fast Downloads',
            'features.fast.desc': 'Lightning-fast download speeds with our optimized servers. Download videos in seconds, not minutes.',
            'features.quality.title': '4K Ultra HD Quality',
            'features.quality.desc': 'Download videos in stunning 4K Ultra HD, 1080p Full HD, 720p HD, and other resolutions.',
            'features.audio.title': 'Audio Extraction',
            'features.audio.desc': 'Extract high-quality MP3 audio from YouTube videos. Perfect for music and podcasts.',
            'features.secure.title': '100% Secure',
            'features.secure.desc': 'Your privacy is our priority. No data collection, no tracking, completely secure downloads.',
            'features.mobile.title': 'Mobile Optimized',
            'features.mobile.desc': 'Works perfectly on all devices - desktop, tablet, and mobile. Responsive design guaranteed.',
            'features.free.title': 'Completely Free',
            'features.free.desc': 'No hidden fees, no registration required. Unlimited downloads forever, completely free.',

            // How it works
            'how.title': 'How to Download YouTube Videos',
            'how.subtitle': 'Simple 3-step process to download any YouTube video',
            'how.step1.title': 'Paste URL',
            'how.step1.desc': 'Copy and paste the YouTube video URL into the input field above.',
            'how.step2.title': 'Choose Quality',
            'how.step2.desc': 'Select your preferred video quality or audio format from available options.',
            'how.step3.title': 'Download',
            'how.step3.desc': 'Click download and save the video to your device. It\'s that simple!',

            // Footer
            'footer.description': 'The world\'s fastest and most reliable YouTube video downloader. Download videos in 4K Ultra HD quality for free.',
            'footer.features': 'Features',
            'footer.support': 'Support',
            'footer.company': 'Company',
            'footer.legal': 'Legal',
            'footer.quality': 'Quality',
            'footer.copyright': 'All rights reserved.',

            // Errors and alerts
            'error.invalid_url': 'Please enter a valid YouTube URL',
            'error.analysis_failed': 'Failed to analyze video',
            'error.download_failed': 'Download failed',
            'error.network_error': 'Network connection failed',
            'error.server_error': 'Server error occurred',
            'error.file_too_large': 'File exceeds size limit',
            'error.rate_limited': 'Too many requests. Please wait.',

            'success.analysis_complete': 'Video analysis completed',
            'success.download_started': 'Download started successfully',
            'success.download_complete': 'Download completed successfully',

            'info.processing': 'Processing your request...',
            'info.please_wait': 'Please wait...',
            'info.loading': 'Loading...',

            // About page
            'about.title': 'About YT Ultra HD',
            'about.mission': 'Our Mission',
            'about.mission.desc': 'To democratize access to video content by providing the fastest, most reliable, and completely free YouTube video downloading service in the world.',
            'about.stats.title': 'Live Performance Stats',
            'about.stats.desc': 'Real-time data from our ultra-fast backend servers',
            'about.stats.requests': 'Total Requests',
            'about.stats.downloads': 'Active Downloads',
            'about.stats.response': 'Avg Response Time',
            'about.stats.cache': 'Cache Hit Rate',

            // Contact page
            'contact.title': 'Get in Touch',
            'contact.subtitle': 'Have questions, feedback, or need help? We\'re here to assist you with any issues related to YouTube video downloads.',
            'contact.form.title': 'Send us a Message',
            'contact.form.firstname': 'First Name',
            'contact.form.lastname': 'Last Name',
            'contact.form.email': 'Email Address',
            'contact.form.subject': 'Subject',
            'contact.form.message': 'Message',
            'contact.form.send': 'Send Message',
            'contact.form.reset': 'Reset Form',
            'contact.response.fast': 'Fast Response Guaranteed',
            'contact.response.desc': 'We\'re committed to providing quick and helpful responses to all your queries.',

            // Common actions
            'action.close': 'Close',
            'action.cancel': 'Cancel',
            'action.confirm': 'Confirm',
            'action.save': 'Save',
            'action.delete': 'Delete',
            'action.edit': 'Edit',
            'action.copy': 'Copy',
            'action.share': 'Share',
            'action.print': 'Print',
            'action.refresh': 'Refresh',
            'action.back': 'Back',
            'action.next': 'Next',
            'action.previous': 'Previous',

            // Time and dates
            'time.seconds': 'seconds',
            'time.minutes': 'minutes',
            'time.hours': 'hours',
            'time.days': 'days',
            'time.just_now': 'just now',
            'time.ago': 'ago',

            // File sizes
            'size.bytes': 'B',
            'size.kb': 'KB',
            'size.mb': 'MB',
            'size.gb': 'GB',
            'size.tb': 'TB'
        };

        this.translations.set('en', defaultTranslations);
        this.loadedLanguages.add('en');
        console.log('🌐 Default translations loaded');
    }

    // Load translations for a specific language
    async loadLanguage(lang) {
        if (this.loadedLanguages.has(lang)) {
            console.log(`🌐 Language ${lang} already loaded`);
            return true;
        }

        try {
            // In a real implementation, you would fetch from your backend
            // For now, we'll load from static files or generate programmatically
            const translations = await this.fetchTranslations(lang);

            if (translations) {
                this.translations.set(lang, translations);
                this.loadedLanguages.add(lang);
                console.log(`🌐 Language ${lang} loaded successfully`);
                return true;
            }

        } catch (error) {
            console.error(`❌ Failed to load language ${lang}:`, error);
        }

        return false;
    }

    // Fetch translations (could be from backend API)
    async fetchTranslations(lang) {
        // In a real implementation, this would fetch from your backend
        // Example: const response = await fetch(`/api/translations/${lang}`);

        // For demo purposes, we'll return a subset for Spanish
        if (lang === 'es') {
            return {
                'nav.home': 'Inicio',
                'nav.download': 'Descargar',
                'nav.4k-videos': 'Videos 4K',
                'nav.about': 'Acerca de',
                'nav.contact': 'Contacto',
                'hero.title': 'Descargar Videos de YouTube en Ultra HD 4K',
                'hero.subtitle': 'Descargador de videos de YouTube gratuito, rápido e ilimitado. Descarga videos en 4K, HD, o extrae audio en formato MP3. No requiere registro.',
                'hero.url.placeholder': 'Pega la URL de YouTube aquí...',
                'hero.analyze.button': 'Analizar Video',
                'hero.analyze.loading': 'Analizando...',
                'features.title': '¿Por qué elegir YT Ultra HD?',
                'features.fast.title': 'Descargas Ultra-Rápidas',
                'features.quality.title': 'Calidad 4K Ultra HD',
                'features.audio.title': 'Extracción de Audio',
                'features.secure.title': '100% Seguro',
                'features.mobile.title': 'Optimizado para Móviles',
                'features.free.title': 'Completamente Gratis',
                'download.progress': 'Progreso de Descarga',
                'download.completed': '¡Descarga Completa!',
                'error.invalid_url': 'Por favor ingresa una URL válida de YouTube',
                'success.download_complete': 'Descarga completada exitosamente'
            };
        }

        // For other languages, return null (would trigger fallback)
        return null;
    }

    // Get translation
    t(key, params = {}) {
        let translation = this.getTranslation(key, this.currentLanguage);

        // Fallback to English if translation not found
        if (!translation && this.currentLanguage !== this.fallbackLanguage) {
            translation = this.getTranslation(key, this.fallbackLanguage);
        }

        // Fallback to key if no translation found
        if (!translation) {
            console.warn(`🌐 Translation missing for key: ${key}`);
            translation = key;
        }

        // Replace parameters
        return this.replaceParams(translation, params);
    }

    getTranslation(key, lang) {
        const langTranslations = this.translations.get(lang);
        return langTranslations ? langTranslations[key] : null;
    }

    replaceParams(text, params) {
        return text.replace(/\{\{(\w+)\}\}/g, (match, paramName) => {
            return params[paramName] !== undefined ? params[paramName] : match;
        });
    }

    // Change language
    async changeLanguage(lang) {
        if (!this.isValidLanguage(lang)) {
            console.warn(`🌐 Invalid language: ${lang}`);
            return false;
        }

        // Load language if not already loaded
        if (!this.loadedLanguages.has(lang)) {
            const loaded = await this.loadLanguage(lang);
            if (!loaded && lang !== this.fallbackLanguage) {
                console.warn(`🌐 Failed to load language ${lang}, falling back to ${this.fallbackLanguage}`);
                lang = this.fallbackLanguage;
            }
        }

        const oldLanguage = this.currentLanguage;
        this.currentLanguage = lang;

        // Save preference
        this.saveLanguagePreference(lang);

        // Update page direction
        this.updatePageDirection();

        // Update all translatable elements
        this.updatePageTranslations();

        // Notify observers
        this.notifyLanguageChange(oldLanguage, lang);

        // Track language change
        if (window.Analytics) {
            window.Analytics.track('language_changed', {
                from: oldLanguage,
                to: lang,
                isRTL: this.isRTL(lang)
            });
        }

        console.log(`🌐 Language changed from ${oldLanguage} to ${lang}`);
        return true;
    }

    // Update page direction for RTL languages
    updatePageDirection() {
        const isRTL = this.isRTL(this.currentLanguage);
        document.documentElement.dir = isRTL ? 'rtl' : 'ltr';
        document.documentElement.lang = this.currentLanguage;

        // Update body class for RTL styling
        document.body.classList.toggle('rtl', isRTL);

        console.log(`🌐 Page direction updated: ${isRTL ? 'RTL' : 'LTR'}`);
    }

    isRTL(lang) {
        return this.rtlLanguages.includes(lang);
    }

    // Update all translatable elements on the page
    updatePageTranslations() {
        // Update elements with data-i18n attribute
        document.querySelectorAll('[data-i18n]').forEach(element => {
            const key = element.getAttribute('data-i18n');
            const translation = this.t(key);

            if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
                element.placeholder = translation;
            } else {
                element.textContent = translation;
            }
        });

        // Update elements with data-i18n-html attribute (for HTML content)
        document.querySelectorAll('[data-i18n-html]').forEach(element => {
            const key = element.getAttribute('data-i18n-html');
            const translation = this.t(key);
            element.innerHTML = translation;
        });

        // Update title and meta description
        this.updatePageMeta();

        console.log('🌐 Page translations updated');
    }

    // Update page meta information
    updatePageMeta() {
        const path = window.location.pathname;
        let titleKey = 'meta.title.home';
        let descKey = 'meta.desc.home';

        // Determine title and description keys based on current page
        if (path.includes('/about')) {
            titleKey = 'meta.title.about';
            descKey = 'meta.desc.about';
        } else if (path.includes('/contact')) {
            titleKey = 'meta.title.contact';
            descKey = 'meta.desc.contact';
        } else if (path.includes('/download')) {
            titleKey = 'meta.title.download';
            descKey = 'meta.desc.download';
        }

        // Update title
        const title = this.t(titleKey);
        if (title !== titleKey) {
            document.title = title;
        }

        // Update meta description
        const desc = this.t(descKey);
        if (desc !== descKey) {
            const metaDesc = document.querySelector('meta[name="description"]');
            if (metaDesc) {
                metaDesc.content = desc;
            }
        }
    }

    // Setup language selector
    setupLanguageSelector() {
        const selector = document.getElementById('languageSelector');
        if (!selector) return;

        const languages = this.getSupportedLanguages();

        // Create language options
        selector.innerHTML = Object.entries(languages).map(([code, info]) => {
            const selected = code === this.currentLanguage ? 'selected' : '';
            return `<option value="${code}" ${selected}>${info.flag} ${info.nativeName}</option>`;
        }).join('');

        // Handle language change
        selector.addEventListener('change', (e) => {
            this.changeLanguage(e.target.value);
        });
    }

    // Setup mutation observer for new content
    setupLanguageObserver() {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // Translate new elements
                        const translatableElements = node.querySelectorAll('[data-i18n], [data-i18n-html]');
                        translatableElements.forEach(element => {
                            this.translateElement(element);
                        });

                        // Check if the node itself is translatable
                        if (node.hasAttribute && (node.hasAttribute('data-i18n') || node.hasAttribute('data-i18n-html'))) {
                            this.translateElement(node);
                        }
                    }
                });
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });

        this.observers.add(observer);
    }

    translateElement(element) {
        if (element.hasAttribute('data-i18n')) {
            const key = element.getAttribute('data-i18n');
            const translation = this.t(key);

            if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
                element.placeholder = translation;
            } else {
                element.textContent = translation;
            }
        }

        if (element.hasAttribute('data-i18n-html')) {
            const key = element.getAttribute('data-i18n-html');
            const translation = this.t(key);
            element.innerHTML = translation;
        }
    }

    // Save language preference
    saveLanguagePreference(lang) {
        try {
            localStorage.setItem('yt-language', lang);
        } catch (error) {
            console.warn('🌐 Could not save language preference:', error);
        }
    }

    // Language change notification system
    onLanguageChange(callback) {
        this.observers.add(callback);
    }

    offLanguageChange(callback) {
        this.observers.delete(callback);
    }

    notifyLanguageChange(oldLang, newLang) {
        this.observers.forEach(callback => {
            if (typeof callback === 'function') {
                try {
                    callback(oldLang, newLang);
                } catch (error) {
                    console.error('🌐 Language change callback error:', error);
                }
            }
        });
    }

    // Utility methods
    getCurrentLanguage() {
        return this.currentLanguage;
    }

    getCurrentLanguageInfo() {
        return this.getSupportedLanguages()[this.currentLanguage];
    }

    isCurrentLanguageRTL() {
        return this.isRTL(this.currentLanguage);
    }

    getLoadedLanguages() {
        return Array.from(this.loadedLanguages);
    }

    // Format numbers according to current locale
    formatNumber(number) {
        try {
            return new Intl.NumberFormat(this.currentLanguage).format(number);
        } catch (error) {
            return number.toString();
        }
    }

    // Format dates according to current locale
    formatDate(date, options = {}) {
        try {
            return new Intl.DateTimeFormat(this.currentLanguage, options).format(date);
        } catch (error) {
            return date.toString();
        }
    }

    // Format relative time
    formatRelativeTime(date) {
        try {
            const rtf = new Intl.RelativeTimeFormat(this.currentLanguage, { numeric: 'auto' });
            const now = new Date();
            const diffInSeconds = Math.round((date - now) / 1000);

            if (Math.abs(diffInSeconds) < 60) {
                return rtf.format(diffInSeconds, 'second');
            } else if (Math.abs(diffInSeconds) < 3600) {
                return rtf.format(Math.round(diffInSeconds / 60), 'minute');
            } else if (Math.abs(diffInSeconds) < 86400) {
                return rtf.format(Math.round(diffInSeconds / 3600), 'hour');
            } else {
                return rtf.format(Math.round(diffInSeconds / 86400), 'day');
            }
        } catch (error) {
            return date.toString();
        }
    }

    // Cleanup
    destroy() {
        this.observers.forEach(observer => {
            if (observer.disconnect) {
                observer.disconnect();
            }
        });
        this.observers.clear();
        this.translations.clear();
        this.loadedLanguages.clear();
    }
}

// Auto-initialize
document.addEventListener('DOMContentLoaded', () => {
    window.i18n = new I18nManager();

    // Make translation function globally available
    window.t = (key, params) => window.i18n.t(key, params);
});

// Export for global access
window.I18nManager = I18nManager;