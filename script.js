// ===== Navigation scroll effect =====
const nav = document.getElementById('nav');

window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 50);
}, { passive: true });

// ===== Mobile menu toggle =====
const navToggle = document.getElementById('nav-toggle');
const mobileMenu = document.getElementById('mobile-menu');

navToggle.addEventListener('click', () => {
    const isOpen = mobileMenu.classList.toggle('open');
    navToggle.classList.toggle('active');
    navToggle.setAttribute('aria-expanded', isOpen);
    document.body.style.overflow = isOpen ? 'hidden' : '';
});

// Close mobile menu on link click
mobileMenu.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => {
        navToggle.classList.remove('active');
        mobileMenu.classList.remove('open');
        navToggle.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
    });
});

// ===== Scroll reveal animations =====
const revealElements = document.querySelectorAll(
    '.section-label, .section-title, .about-text p, .stat-card, .about-video, .venture-card, .timeline-item, .press-logo, .newsletter-desc, .newsletter-btn, .book-subtitle, .book-desc, .book-chapters, .book-btn, .personal-text, .contact-desc, .social-links'
);

revealElements.forEach(el => el.classList.add('reveal'));

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
            observer.unobserve(entry.target);
        }
    });
}, {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
});

revealElements.forEach(el => observer.observe(el));

// ===== Smooth scroll for nav links =====
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', (e) => {
        const target = document.querySelector(anchor.getAttribute('href'));
        if (target) {
            e.preventDefault();
            const offset = nav.offsetHeight + 20;
            const top = target.getBoundingClientRect().top + window.scrollY - offset;
            window.scrollTo({ top, behavior: 'smooth' });
        }
    });
});
