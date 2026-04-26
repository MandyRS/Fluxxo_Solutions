// Filtro de tipo de movimentação na aba Fluxo de Estoque
document.addEventListener('DOMContentLoaded', function() {
    var filtroTipo = document.getElementById('filtroTipoMov');
    if (filtroTipo) {
        filtroTipo.addEventListener('change', function() {
            var tipo = this.value;
            var linhas = document.querySelectorAll('#tabelaFluxoEstoque tbody tr');
            linhas.forEach(function(tr) {
                // Pega o texto da célula "Tipo" (quarta coluna, index 3)
                var tdTipo = tr.querySelectorAll('td')[3];
                if (!tdTipo) return;
                var valor = tdTipo.textContent.trim().toLowerCase();
                if (!tipo || valor === tipo.toLowerCase()) {
                    tr.style.display = '';
                } else {
                    tr.style.display = 'none';
                }
            });
        });
    }
});
// Efeito de rolagem na Navbar
window.addEventListener('scroll', () => {
    const nav = document.querySelector('.navbar');
    if (window.scrollY > 50) {
        nav.style.padding = '15px 8%';
        nav.style.boxShadow = '0 4px 6px -1px rgba(0,0,0,0.1)';
    } else {
        nav.style.padding = '20px 8%';
        nav.style.boxShadow = 'none';
    }
});

// Animação simples de entrada para o card de dashboard
document.addEventListener('DOMContentLoaded', () => {
    const card = document.querySelector('.glass-card');
    card.style.opacity = '0';
    card.style.transform = 'translateY(20px)';
    
    setTimeout(() => {
        card.style.transition = 'all 1s ease-out';
        card.style.opacity = '1';
        card.style.transform = 'perspective(1000px) rotateY(-15deg)';
    }, 300);
});
