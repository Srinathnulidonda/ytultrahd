// Internationalization support
class I18n {
    constructor() {
        this.currentLocale = this.detectLocale();
        this.translations = {};
        this.rtlLanguages = ['ar', 'he', 'fa', 'ur'];
        this.loadTranslations();
    }

    // Detect user's preferred language
    detectLocale() {
        // Check localStorage
        const saved = localStorage.getItem('locale');
        if (saved) return saved;

        // Check navigator
        const browserLang = navigator.language || navigator.userLanguage;
        const shortLang = browserLang.split('-')[0];

        // Supported languages
        const supported = ['en', 'es', 'fr', 'de', 'pt', 'ar', 'hi', 'zh', 'ja', 'ko'];

        return supported.includes(shortLang) ? shortLang : 'en';
    }

    // Load translations
    async loadTranslations() {
        // Default English translations
        this.translations.en = {
            'app.name': 'YT Ultra',
            'app.tagline': 'Fastest YouTube Downloader',
            'home.title': 'Download YouTube Videos Ultra Fast',
            'home.paste_url': 'Paste YouTube URL here...',
            'home.paste_button': 'Paste',
            'home.get_info': 'Get Video Info',
            'home.start_download': 'Start Download',
            'home.select_quality': 'Select Quality',
            'home.downloading': 'Downloading...',
            'home.download_complete': 'Download Complete!',
            'features.fast': 'Ultra Fast',
            'features.fast_desc': 'Multi-threaded downloads with speeds up to 100MB/s',
            'features.quality': 'High Quality',
            'features.quality_desc': 'Support for 4K resolution and lossless audio',
            'features.safe': '100% Safe',
            'features.safe_desc': 'No ads, no malware, just pure downloads',
            'nav.home': 'Home',
            'nav.about': 'About',
            'nav.contact': 'Contact',
            'nav.history': 'History',
            'error.invalid_url': 'Please enter a valid YouTube URL',
            'error.download_failed': 'Download failed. Please try again.',
            'error.network': 'Network error. Please check your connection.',
            'success.download_started': 'Download started!',
            'success.download_complete': 'Download completed!',
            'time.seconds': '{n} seconds',
            'time.minutes': '{n} minutes',
            'time.hours': '{n} hours',
            'size.bytes': '{n} bytes',
            'size.kb': '{n} KB',
            'size.mb': '{n} MB',
            'size.gb': '{n} GB'
        };

        // Load additional translations based on locale
        if (this.currentLocale !== 'en') {
            try {
                const response = await fetch(`/locales/${this.currentLocale}.json`);
                if (response.ok) {
                    this.translations[this.currentLocale] = await response.json();
                }
            } catch (error) {
                console.warn(`Failed to load translations for ${this.currentLocale}`);
            }
        }

        // Apply RTL if needed
        this.applyRTL();

        // Translate current page
        this.translatePage();
    }

    // Get translation
    t(key, params = {}) {
        const translations = this.translations[this.currentLocale] || this.translations.en;
        let text = translations[key] || key;

        // Replace parameters
        Object.keys(params).forEach(param => {
            text = text.replace(`{${param}}`, params[param]);
        });

        return text;
    }

    // Change language
    setLocale(locale) {
        this.currentLocale = locale;
        localStorage.setItem('locale', locale);
        this.loadTranslations();

        // Dispatch event
        window.dispatchEvent(new CustomEvent('localeChanged', { detail: locale }));
    }

    // Apply RTL styling
    applyRTL() {
        const isRTL = this.rtlLanguages.includes(this.currentLocale);
        document.documentElement.dir = isRTL ? 'rtl' : 'ltr';
        document.documentElement.lang = this.currentLocale;

        // Add RTL class for custom styling
        if (isRTL) {
            document.body.classList.add('rtl');
        } else {
            document.body.classList.remove('rtl');
        }
    }

    // Translate page elements
    translatePage() {
        // Translate elements with data-i18n attribute
        document.querySelectorAll('[data-i18n]').forEach(element => {
            const key = element.getAttribute('data-i18n');
            element.textContent = this.t(key);
        });

        // Translate placeholders
        document.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
            const key = element.getAttribute('data-i18n-placeholder');
            element.placeholder = this.t(key);
        });

        // Translate titles
        document.querySelectorAll('[data-i18n-title]').forEach(element => {
            const key = element.getAttribute('data-i18n-title');
            element.title = this.t(key);
        });

        // Update document title
        if (document.title.includes('YT Ultra')) {
            document.title = document.title.replace('YT Ultra', this.t('app.name'));
        }
    }

    // Format numbers based on locale
    formatNumber(number) {
        return new Intl.NumberFormat(this.currentLocale).format(number);
    }

    // Format dates based on locale
    formatDate(date, options = {}) {
        return new Intl.DateTimeFormat(this.currentLocale, options).format(date);
    }

    // Format relative time
    formatRelativeTime(date) {
        const rtf = new Intl.RelativeTimeFormat(this.currentLocale, { numeric: 'auto' });
        const diff = date - new Date();
        const diffInSeconds = diff / 1000;
        const diffInMinutes = diffInSeconds / 60;
        const diffInHours = diffInMinutes / 60;
        const diffInDays = diffInHours / 24;

        if (Math.abs(diffInDays) >= 1) {
            return rtf.format(Math.round(diffInDays), 'day');
        } else if (Math.abs(diffInHours) >= 1) {
            return rtf.format(Math.round(diffInHours), 'hour');
        } else if (Math.abs(diffInMinutes) >= 1) {
            return rtf.format(Math.round(diffInMinutes), 'minute');
        } else {
            return rtf.format(Math.round(diffInSeconds), 'second');
        }
    }

    // Get available languages
    getAvailableLanguages() {
        return [
            { code: 'en', name: 'English', native: 'English' },
            { code: 'es', name: 'Spanish', native: 'Español' },
            { code: 'fr', name: 'French', native: 'Français' },
            { code: 'de', name: 'German', native: 'Deutsch' },
            { code: 'pt', name: 'Portuguese', native: 'Português' },
            { code: 'ar', name: 'Arabic', native: 'العربية' },
            { code: 'hi', name: 'Hindi', native: 'हिन्दी' },
            { code: 'zh', name: 'Chinese', native: '中文' },
            { code: 'ja', name: 'Japanese', native: '日本語' },
            { code: 'ko', name: 'Korean', native: '한국어' }
        ];
    }
}

// Initialize i18n
const i18n = new I18n();

// Export
if (typeof window !== 'undefined') {
    window.i18n = i18n;
}

export default i18n;