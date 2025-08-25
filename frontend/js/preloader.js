// Advanced preloader with skeleton screens and progressive loading
class PreloaderManager {
    constructor() {
        this.activeLoaders = new Map();
        this.defaultOptions = {
            shimmer: true,
            fadeIn: true,
            minDuration: 300,
            progressiveReveal: true
        };
    }

    // Create skeleton loader
    createSkeleton(type = 'text', options = {}) {
        const config = { ...this.defaultOptions, ...options };
        const skeleton = document.createElement('div');
        skeleton.className = 'skeleton';

        switch (type) {
            case 'text':
                skeleton.classList.add('skeleton-text');
                skeleton.style.width = options.width || '100%';
                skeleton.style.height = options.height || '1rem';
                break;

            case 'title':
                skeleton.classList.add('skeleton-title');
                skeleton.style.width = options.width || '60%';
                skeleton.style.height = options.height || '1.5rem';
                break;

            case 'thumbnail':
                skeleton.classList.add('skeleton-thumbnail');
                skeleton.style.width = options.width || '100%';
                skeleton.style.height = options.height || '200px';
                break;

            case 'avatar':
                skeleton.classList.add('skeleton-avatar');
                skeleton.style.width = options.width || '48px';
                skeleton.style.height = options.height || '48px';
                skeleton.style.borderRadius = '50%';
                break;

            case 'button':
                skeleton.classList.add('skeleton-button');
                skeleton.style.width = options.width || '120px';
                skeleton.style.height = options.height || '40px';
                skeleton.style.borderRadius = '0.5rem';
                break;

            case 'card':
                return this.createCardSkeleton(options);

            case 'list':
                return this.createListSkeleton(options);

            default:
                skeleton.style.width = options.width || '100%';
                skeleton.style.height = options.height || '1rem';
        }

        if (config.shimmer) {
            skeleton.classList.add('skeleton-shimmer');
        }

        return skeleton;
    }

    // Create card skeleton
    createCardSkeleton(options = {}) {
        const card = document.createElement('div');
        card.className = 'skeleton-card p-4 rounded-xl bg-white shadow-sm';

        // Thumbnail
        const thumbnail = this.createSkeleton('thumbnail', { height: '180px' });
        card.appendChild(thumbnail);

        // Title
        const title = this.createSkeleton('title', { width: '70%' });
        title.classList.add('mt-3');
        card.appendChild(title);

        // Text lines
        for (let i = 0; i < (options.lines || 3); i++) {
            const text = this.createSkeleton('text', {
                width: i === options.lines - 1 ? '80%' : '100%'
            });
            text.classList.add('mt-2');
            card.appendChild(text);
        }

        // Button
        if (options.button) {
            const button = this.createSkeleton('button', { width: '100%' });
            button.classList.add('mt-4');
            card.appendChild(button);
        }

        return card;
    }

    // Create list skeleton
    createListSkeleton(options = {}) {
        const list = document.createElement('div');
        list.className = 'skeleton-list';

        const items = options.items || 5;
        for (let i = 0; i < items; i++) {
            const item = document.createElement('div');
            item.className = 'skeleton-list-item flex items-center p-3 mb-2';

            // Avatar
            const avatar = this.createSkeleton('avatar', { width: '40px', height: '40px' });
            item.appendChild(avatar);

            // Content
            const content = document.createElement('div');
            content.className = 'ml-3 flex-1';

            const title = this.createSkeleton('text', { width: '60%', height: '1rem' });
            const subtitle = this.createSkeleton('text', { width: '40%', height: '0.875rem' });
            subtitle.classList.add('mt-1', 'opacity-70');

            content.appendChild(title);
            content.appendChild(subtitle);
            item.appendChild(content);

            list.appendChild(item);
        }

        return list;
    }

    // Show loader
    show(container, type = 'text', options = {}) {
        const startTime = Date.now();
        const loaderId = `loader_${Date.now()}_${Math.random()}`;

        // Store original content
        const originalContent = container.innerHTML;
        this.activeLoaders.set(loaderId, {
            container,
            originalContent,
            startTime
        });

        // Clear container and add skeleton
        container.innerHTML = '';
        const skeleton = this.createSkeleton(type, options);
        container.appendChild(skeleton);

        return loaderId;
    }

    // Hide loader
    async hide(loaderId, newContent = null) {
        const loader = this.activeLoaders.get(loaderId);
        if (!loader) return;

        const { container, originalContent, startTime } = loader;
        const elapsed = Date.now() - startTime;

        // Ensure minimum duration
        if (elapsed < this.defaultOptions.minDuration) {
            await this.delay(this.defaultOptions.minDuration - elapsed);
        }

        // Fade out skeleton
        if (this.defaultOptions.fadeIn) {
            container.style.opacity = '0';
            container.style.transition = 'opacity 0.2s ease-out';

            await this.delay(200);

            // Replace content
            container.innerHTML = newContent || originalContent;

            // Fade in new content
            requestAnimationFrame(() => {
                container.style.opacity = '1';
            });

            // Clean up
            setTimeout(() => {
                container.style.transition = '';
            }, 200);
        } else {
            container.innerHTML = newContent || originalContent;
        }

        this.activeLoaders.delete(loaderId);
    }

    // Video info skeleton
    showVideoInfoSkeleton(container) {
        const skeleton = document.createElement('div');
        skeleton.className = 'video-info-skeleton';
        skeleton.innerHTML = `
            <div class="row g-3">
                <div class="col-md-4">
                    ${this.createSkeleton('thumbnail', { height: '180px' }).outerHTML}
                </div>
                <div class="col-md-8">
                    ${this.createSkeleton('title', { width: '80%' }).outerHTML}
                    <div class="mt-3">
                        ${this.createSkeleton('text', { width: '60%' }).outerHTML}
                    </div>
                    <div class="mt-2">
                        ${this.createSkeleton('text', { width: '100%' }).outerHTML}
                        ${this.createSkeleton('text', { width: '90%' }).outerHTML}
                        ${this.createSkeleton('text', { width: '70%' }).outerHTML}
                    </div>
                </div>
            </div>
        `;

        container.innerHTML = '';
        container.appendChild(skeleton);
        container.classList.remove('d-none');
    }

    // Progress skeleton
    showProgressSkeleton(container) {
        const skeleton = document.createElement('div');
        skeleton.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-2">
                ${this.createSkeleton('text', { width: '120px', height: '1rem' }).outerHTML}
                ${this.createSkeleton('text', { width: '60px', height: '1rem' }).outerHTML}
            </div>
            <div class="progress skeleton" style="height: 8px;">
                <div class="progress-bar" style="width: 0%"></div>
            </div>
            <div class="d-flex justify-content-between mt-2">
                ${this.createSkeleton('text', { width: '80px', height: '0.875rem' }).outerHTML}
                ${this.createSkeleton('text', { width: '100px', height: '0.875rem' }).outerHTML}
            </div>
        `;

        container.innerHTML = '';
        container.appendChild(skeleton);
    }

    // LQIP (Low Quality Image Placeholder)
    async loadImageWithLQIP(img, highResSrc, lqipSrc) {
        // Load LQIP first
        if (lqipSrc) {
            img.src = lqipSrc;
            img.style.filter = 'blur(10px)';
            img.style.transition = 'filter 0.3s ease-out';
        }

        // Load high-res image
        const highResImg = new Image();
        highResImg.src = highResSrc;

        return new Promise((resolve) => {
            highResImg.onload = () => {
                img.src = highResSrc;
                img.style.filter = 'none';
                resolve();
            };

            highResImg.onerror = () => {
                img.style.filter = 'none';
                resolve();
            };
        });
    }

    // Utility
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// Export singleton
const preloader = new PreloaderManager();

if (typeof window !== 'undefined') {
    window.preloader = preloader;
}

export default preloader;