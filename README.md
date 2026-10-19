# ⚖️ Tribunal Bot de Discord

Un bot para Discord hecho en Python (`discord.py`) para gestionar juicios cómicos en servidores con amigos.

## 🚀 Funcionalidades
- `!juicio @acusado [motivo]`: Crea la categoría privada con canales de voz y texto.
- Votaciones de veredicto y propuestas de castigos cómicos en tiempo real.
- Asignación de abogado fiscal (`!abogado_fiscal`) y de defensa (`!abogado_defensa`).
- Panel de configuración por rol con `!config`.
- `!cerrar_juicio`: Muestra la sentencia y elimina los canales automáticamente.

## ⚙️ Instalación Local
1. Instala dependencias: `pip install -r requirements.txt`
2. Crea un archivo `.env` con: `DISCORD_TOKEN=tu_token_aqui`
3. Ejecuta: `python bot.py`