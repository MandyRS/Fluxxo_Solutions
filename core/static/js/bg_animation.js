// bg_animation.js
document.addEventListener('DOMContentLoaded', () => {
    const bgContainer = document.getElementById('bgAnimation');
    const orbsCount = 3; // Número de esferas de fundo

    for (let i = 0; i < orbsCount; i++) {
        const orb = document.createElement('div');
        orb.classList.add('orb');
        
        // Estilização aleatória básica via JS para cada orbe
        const size = Math.random() * 300 + 200; // Entre 200px e 500px
        orb.style.width = `${size}px`;
        orb.style.height = `${size}px`;
        
        // Posição inicial aleatória
        orb.style.top = `${Math.random() * 100}%`;
        orb.style.left = `${Math.random() * 100}%`;
        
        // Cores suaves baseadas no azul primário
        orb.style.background = `radial-gradient(circle, rgba(0,85,255,0.08) 0%, rgba(0,85,255,0) 70%)`;
        orb.style.position = 'absolute';
        orb.style.borderRadius = '50%';
        orb.style.filter = 'blur(40px)';
        orb.style.zIndex = '1';
        
        // Animação CSS inline para movimento lento e aleatório
        const duration = Math.random() * 20 + 10; // Entre 10s e 30s
        orb.style.animation = `floatOrb ${duration}s infinite linear alternate`;

        bgContainer.appendChild(orb);
    }
});

// Adiciona a animação keyframes dinamicamente
const style = document.createElement('style');
style.type = 'text/css';
style.innerHTML = `
    @keyframes floatOrb {
        0% { transform: translate(0, 0); }
        100% { transform: translate(${Math.random() * 100 - 50}px, ${Math.random() * 100 - 50}px); }
    }
`;
document.getElementsByTagName('head')[0].appendChild(style);