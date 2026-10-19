import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

juicios_activos = {}
configuracion_servidores = {}

EMOJIS_NUMEROS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

# ---------------------------------------------------------
# FUNCION AUXILIAR: OBTENER USUARIOS EXCLUIDOS DE VOTOS
# ---------------------------------------------------------
def obtener_excluidos(datos_juicio: dict) -> set:
    """Devuelve el conjunto de IDs del denunciante, acusado y sus respectivos abogados."""
    excluidos = {
        datos_juicio.get("denunciante"),
        datos_juicio.get("acusado"),
        datos_juicio.get("abogado_fiscal"),
        datos_juicio.get("abogado_defensa")
    }
    return {uid for uid in excluidos if uid is not None}


# ---------------------------------------------------------
# FUNCION AUXILIAR: GENERAR EMBED DE LEYES
# ---------------------------------------------------------
def obtener_embed_leyes():
    embed = discord.Embed(
        title="🏛️ CÓDIGO PENAL Y MANUAL DEL TRIBUNAL ⚖️",
        description="Guía rápida para la sesión del juicio:",
        color=discord.Color.dark_gold()
    )
    embed.add_field(
        name="🚨 1. Inicio de Juicio",
        value="`!juicio @acusado [motivo]`\nCrea la categoría privada y los canales del juicio.",
        inline=False
    )
    embed.add_field(
        name="⚖️ 2. Asignación de Abogados y Participantes",
        value=(
            "`!abogado_fiscal @amigo` — Asigna tu fiscal (solo acusador).\n"
            "`!abogado_defensa @amigo` — Asigna tu defensa (solo acusado).\n"
            "`!añadir_participante @usuario` — Da acceso a alguien sin rol."
        ),
        inline=False
    )
    embed.add_field(
        name="📜 3. Castigos y Votación",
        value=(
            "• **#veredicto-y-votacion**: Vota si gana el acusador o el acusado.\n"
            "• **#propuestas-castigos**: Propón un castigo y vota en las reacciones.\n"
            "⚠️ *Nota: El acusado, denunciante y abogados tienen prohibido votar o proponer.*"
        ),
        inline=False
    )
    embed.add_field(
        name="🔨 4. Finalización",
        value="`!cerrar_juicio` — Cierra la sesión, determina los ganadores y borra la categoría.",
        inline=False
    )
    embed.set_footer(text="Tribunal Bot • La justicia es ciega pero el código no.")
    return embed


# ---------------------------------------------------------
# 1. MODAL Y VISTA PARA PROPONER CASTIGOS (RESTRICCIONES ACTIVAS)
# ---------------------------------------------------------
class ModalCastigo(discord.ui.Modal, title="Proponer Castigo Cómico"):
    castigo_input = discord.ui.TextInput(
        label="¿Cuál es tu propuesta de castigo?",
        style=discord.TextStyle.paragraph,
        placeholder="Ej: Fregar los suelos de la base de Minecraft por 1 semana.",
        required=True,
        max_length=200
    )

    def __init__(self, category_id: int, message_to_update: discord.Message):
        super().__init__()
        self.category_id = category_id
        self.message_to_update = message_to_update

    async def on_submit(self, interaction: discord.Interaction):
        datos_juicio = juicios_activos.get(self.category_id)
        if not datos_juicio:
            await interaction.response.send_message("Este juicio ya no está activo.", ephemeral=True)
            return

        propuesta = self.castigo_input.value.strip()
        autor_nombre = interaction.user.display_name
        autor_id = interaction.user.id

        castigos = datos_juicio["castigos"]
        encontrado = False
        for c in castigos:
            if c.get("autor_id") == autor_id:
                c["texto"] = propuesta
                encontrado = True
                break

        if not encontrado:
            if len(castigos) >= len(EMOJIS_NUMEROS):
                await interaction.response.send_message("❌ Se ha alcanzado el límite máximo de castigos propuestos (10).", ephemeral=True)
                return
            castigos.append({"autor_id": autor_id, "autor": autor_nombre, "texto": propuesta})
            nuevo_index = len(castigos) - 1
            await self.message_to_update.add_reaction(EMOJIS_NUMEROS[nuevo_index])

        embed = self.message_to_update.embeds[0]
        lista_txt = "\n".join([f"{EMOJIS_NUMEROS[i]} **{c['autor']}**: {c['texto']}" for i, c in enumerate(castigos)])
        
        embed.description = (
            "Haz clic en el botón de abajo para proponer un castigo para el juicio actual.\n"
            "⚠️ *El acusado, el denunciante y sus respectivos abogados tienen prohibido proponer.*\n\n"
            f"**📜 Castigos Propuestos:**\n{lista_txt}"
        )

        await self.message_to_update.edit(embed=embed)
        
        mensaje_respuesta = "✅ ¡Tu propuesta de castigo ha sido actualizada!" if encontrado else "✅ ¡Tu propuesta de castigo ha sido añadida a la lista!"
        await interaction.response.send_message(mensaje_respuesta, ephemeral=True)


class VistaCastigos(discord.ui.View):
    def __init__(self, category_id: int):
        super().__init__(timeout=None)
        self.category_id = category_id

    @discord.ui.button(label="📝 Proponer Castigo", style=discord.ButtonStyle.primary, custom_id="btn_prop_castigo")
    async def proponer(self, interaction: discord.Interaction, button: discord.ui.Button):
        datos_juicio = juicios_activos.get(self.category_id)
        if not datos_juicio:
            await interaction.response.send_message("Juicio no encontrado.", ephemeral=True)
            return

        # VERIFICACIÓN DE SEGURIDAD / RESTRICCIÓN
        if interaction.user.id in obtener_excluidos(datos_juicio):
            await interaction.response.send_message(
                "❌ **Acceso denegado:** Las partes implicadas en el juicio y sus abogados no pueden proponer castigos.",
                ephemeral=True
            )
            return

        message = interaction.message
        await interaction.response.send_modal(ModalCastigo(self.category_id, message))


# ---------------------------------------------------------
# 2. VISTA Y VOTACIÓN DE GANADOR (RESTRICCIONES ACTIVAS)
# ---------------------------------------------------------
class VistaVotacionGanador(discord.ui.View):
    def __init__(self, category_id: int):
        super().__init__(timeout=None)
        self.category_id = category_id

    async def _actualizar_mensaje_votacion(self, interaction: discord.Interaction):
        datos = juicios_activos.get(self.category_id)
        if not datos:
            return

        votos = datos["votos_ganador"]
        votos_acusador = sum(1 for v in votos.values() if v == "Acusador")
        votos_acusado = sum(1 for v in votos.values() if v == "Acusado")

        embed = interaction.message.embeds[0]
        embed.description = (
            f"El juicio está en marcha.\n\n"
            f"**📊 Estado actual de las votaciones:**\n"
            f"🟢 **Gana Acusador:** {votos_acusador} voto(s)\n"
            f"🔴 **Gana Acusado:** {votos_acusado} voto(s)\n\n"
            f"*(Las partes del juicio y abogados tienen prohibido votar)*"
        )
        await interaction.message.edit(embed=embed)

    @discord.ui.button(label="⚖️ Gana el Acusador", style=discord.ButtonStyle.success, custom_id="votar_acusador")
    async def votar_acusador(self, interaction: discord.Interaction, button: discord.ui.Button):
        datos = juicios_activos.get(self.category_id)
        if not datos:
            return

        if interaction.user.id in obtener_excluidos(datos):
            await interaction.response.send_message("❌ Las partes implicadas en el juicio y sus abogados no pueden votar.", ephemeral=True)
            return

        datos["votos_ganador"][interaction.user.id] = "Acusador"
        await self._actualizar_mensaje_votacion(interaction)
        await interaction.response.send_message("✅ Voto registrado: **Gana el Acusador**", ephemeral=True)

    @discord.ui.button(label="⚖️ Gana el Acusado", style=discord.ButtonStyle.danger, custom_id="votar_acusado")
    async def votar_acusado(self, interaction: discord.Interaction, button: discord.ui.Button):
        datos = juicios_activos.get(self.category_id)
        if not datos:
            return

        if interaction.user.id in obtener_excluidos(datos):
            await interaction.response.send_message("❌ Las partes implicadas en el juicio y sus abogados no pueden votar.", ephemeral=True)
            return

        datos["votos_ganador"][interaction.user.id] = "Acusado"
        await self._actualizar_mensaje_votacion(interaction)
        await interaction.response.send_message("✅ Voto registrado: **Gana el Acusado**", ephemeral=True)


# ---------------------------------------------------------
# 3. MENÚ DE CONFIGURACIÓN DE ROL
# ---------------------------------------------------------
class RolSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="Selecciona el rol oficial del Tribunal...", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction):
        rol_seleccionado = self.values[0]
        configuracion_servidores[interaction.guild.id] = rol_seleccionado.id
        await interaction.response.send_message(
            f"✅ ¡Configuración guardada! Rol oficial: **{rol_seleccionado.name}**",
            ephemeral=True
        )

class VistaConfiguracion(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(RolSelect())


@bot.command(name="config")
@commands.has_permissions(administrator=True)
async def config(ctx):
    embed = discord.Embed(
        title="⚙️ CONFIGURACIÓN DEL TRIBUNAL",
        description="Selecciona en el menú desplegable el rol oficial de los miembros del tribunal.",
        color=discord.Color.blurple()
    )
    await ctx.send(embed=embed, view=VistaConfiguracion(), ephemeral=True)

@config.error
async def config_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ **Acceso denegado:** Solo administradores.", ephemeral=True)


# ---------------------------------------------------------
# COMANDOS DE ABOGADOS (FISCAL Y DEFENSA)
# ---------------------------------------------------------
@bot.command(name="abogado_fiscal")
async def abogado_fiscal(ctx, fiscal: discord.Member):
    category = ctx.channel.category
    if not category or category.id not in juicios_activos:
        await ctx.send("❌ Este comando solo se usa dentro de un juicio activo.")
        return

    datos = juicios_activos[category.id]
    if ctx.author.id != datos["denunciante"]:
        await ctx.send("❌ Solo el acusador puede asignar a su abogado fiscal.")
        return

    datos["abogado_fiscal"] = fiscal.id

    # Conceder acceso al canal de voz privado del denunciante
    voz_denunciante = discord.utils.get(category.voice_channels, name="🗣️ Voz Denunciante")
    if voz_denunciante:
        await voz_denunciante.set_permissions(fiscal, connect=True, view_channel=True, speak=True)

    # Darle acceso a la categoría privada
    await category.set_permissions(fiscal, view_channel=True, send_messages=True, read_messages=True)
    await ctx.send(f"⚖️ {fiscal.mention} ha sido asignado como **Abogado Fiscal** de {ctx.author.mention}.")


@bot.command(name="abogado_defensa")
async def abogado_defensa(ctx, defensa: discord.Member):
    category = ctx.channel.category
    if not category or category.id not in juicios_activos:
        await ctx.send("❌ Este comando solo se usa dentro de un juicio activo.")
        return

    datos = juicios_activos[category.id]
    if ctx.author.id != datos["acusado"]:
        await ctx.send("❌ Solo el acusado puede asignar a su abogado defensor.")
        return

    datos["abogado_defensa"] = defensa.id

    # Conceder acceso al canal de voz privado del acusado
    voz_acusado = discord.utils.get(category.voice_channels, name="🗣️ Voz Acusado")
    if voz_acusado:
        await voz_acusado.set_permissions(defensa, connect=True, view_channel=True, speak=True)

    # Darle acceso a la categoría privada
    await category.set_permissions(defensa, view_channel=True, send_messages=True, read_messages=True)
    await ctx.send(f"🛡️ {defensa.mention} ha sido asignado como **Abogado Defensor** de {ctx.author.mention}.")


@bot.command(name="añadir_participante")
async def añadir_participante(ctx, usuario: discord.Member):
    category = ctx.channel.category
    if not category or category.id not in juicios_activos:
        await ctx.send("❌ Este comando solo se puede usar dentro de un juicio activo.")
        return

    datos = juicios_activos[category.id]
    user_id = ctx.author.id
    if user_id != datos["denunciante"] and user_id != datos["acusado"] and not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ Solo las partes implicadas o un administrador pueden añadir participantes.")
        return

    for channel in category.channels:
        await channel.set_permissions(usuario, view_channel=True, send_messages=True, read_messages=True, connect=True)

    await ctx.send(f"✅ ¡Se ha concedido acceso a {usuario.mention}!")


# ---------------------------------------------------------
# GESTIÓN DE REACCIONES (FILTRADO DE EXCLUIDOS + MÁX 1 VOTO)
# ---------------------------------------------------------
@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return

    for cat_id, datos in juicios_activos.items():
        if payload.message_id == datos.get("msg_castigos_id"):
            guild = bot.get_guild(payload.guild_id)
            if not guild:
                return
            member = guild.get_member(payload.user_id)
            if not member:
                return

            channel = guild.get_channel(payload.channel_id)
            msg = await channel.fetch_message(payload.message_id)

            # BLOQUEO DE SEGURIDAD EN REACCIONES PARA INVOLUCRADOS
            if payload.user_id in obtener_excluidos(datos):
                await msg.remove_reaction(payload.emoji, member)
                return

            # Control de máximo 1 voto por usuario
            for reaction in msg.reactions:
                if str(reaction.emoji) != str(payload.emoji):
                    users = [u async for u in reaction.users()]
                    if member in users:
                        await msg.remove_reaction(reaction.emoji, member)


# ---------------------------------------------------------
# COMANDO PRINCIPAL: !juicio
# ---------------------------------------------------------
@bot.command(name="juicio")
async def juicio(ctx, acusado: discord.Member, *, motivo: str = "Sin motivo especificado"):
    guild = ctx.guild
    denunciante = ctx.author

    if acusado == denunciante:
        await ctx.send("¡No puedes juzgarte a ti mismo, puto retresado mental!")
        return
    if acusado.bot:
        await ctx.send("¡Los bots no pueden ser juzgados, puto retresado mental!")
        return

    rol_id = configuracion_servidores.get(guild.id)
    rol_tribunal = guild.get_role(rol_id) if rol_id else None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        bot.user: discord.PermissionOverwrite(view_channel=True, manage_channels=True, manage_permissions=True),
        denunciante: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_messages=True),
        acusado: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_messages=True),
    }

    if rol_tribunal:
        overwrites[rol_tribunal] = discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True)

    category_name = f"⚖️ Juicio | {denunciante.name} vs {acusado.name}"
    category = await guild.create_category(category_name, overwrites=overwrites)

    # 1. Canal #sala-de-pruebas
    c_pruebas = await guild.create_text_channel("sala-de-pruebas", category=category)
    await c_pruebas.send(embed=obtener_embed_leyes())

    public_overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        bot.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }

    # 2. Canal #veredicto-y-votacion
    c_veredicto = await guild.create_text_channel("veredicto-y-votacion", category=category, overwrites=public_overwrites)

    # 3. Canal #propuestas-castigos
    c_castigos = await guild.create_text_channel("propuestas-castigos", category=category, overwrites=public_overwrites)

    # 4. Canales de Voz aislados
    voz_base_overwrites = {
        guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
        bot.user: discord.PermissionOverwrite(connect=True, view_channel=True, manage_channels=True)
    }

    voz_denunciante_overwrites = voz_base_overwrites.copy()
    voz_denunciante_overwrites[denunciante] = discord.PermissionOverwrite(connect=True, view_channel=True, speak=True)
    await guild.create_voice_channel("🗣️ Voz Denunciante", category=category, overwrites=voz_denunciante_overwrites)

    voz_acusado_overwrites = voz_base_overwrites.copy()
    voz_acusado_overwrites[acusado] = discord.PermissionOverwrite(connect=True, view_channel=True, speak=True)
    await guild.create_voice_channel("🗣️ Voz Acusado", category=category, overwrites=voz_acusado_overwrites)

    public_voice = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
        bot.user: discord.PermissionOverwrite(view_channel=True, manage_channels=True)
    }
    await guild.create_voice_channel("🏛️ Pleno del Tribunal", category=category, overwrites=public_voice)

    juicios_activos[category.id] = {
        "denunciante": denunciante.id,
        "acusado": acusado.id,
        "abogado_fiscal": None,
        "abogado_defensa": None,
        "castigos": [],
        "votos_ganador": {},
        "msg_castigos_id": None,
        "msg_castigos_channel_id": c_castigos.id
    }

    embed_veredicto = discord.Embed(
        title="🗳️ VOTACIÓN DE GANADOR",
        description=(
            f"El juicio entre **{denunciante.mention}** y **{acusado.mention}** está en marcha.\n\n"
            f"**📊 Estado actual de las votaciones:**\n"
            f"🟢 **Gana Acusador:** 0 voto(s)\n"
            f"🔴 **Gana Acusado:** 0 voto(s)\n\n"
            f"*(Pulsa los botones de abajo para votar)*"
        ),
        color=discord.Color.blue()
    )
    await c_veredicto.send(embed=embed_veredicto, view=VistaVotacionGanador(category.id))

    embed_castigos = discord.Embed(
        title="⚖️ Propuesta de Castigos",
        description="Haz clic en el botón de abajo para proponer un castigo para el juicio actual.\n"
                    "⚠️ *El acusado, el denunciante y sus respectivos abogados tienen prohibido proponer.*\n\n"
                    "**📜 Castigos Propuestos:**\n*Aún no hay castigos propuestos.*",
        color=discord.Color.gold()
    )
    msg_castigos = await c_castigos.send(embed=embed_castigos, view=VistaCastigos(category.id))
    juicios_activos[category.id]["msg_castigos_id"] = msg_castigos.id

    mencion_destino = rol_tribunal.mention if rol_tribunal else "@everyone (Configura un rol con !config)"

    await ctx.send(
        f"🚨 **¡SE HA CONVOCADO UN JUICIO!** 🚨 {mencion_destino}\n"
        f"Canales creados en **{category_name}**."
    )


# ---------------------------------------------------------
# COMANDO: !cerrar_juicio
# ---------------------------------------------------------
@bot.command(name="cerrar_juicio")
async def cerrar_juicio(ctx):
    category = ctx.channel.category
    if not category or category.id not in juicios_activos:
        await ctx.send("❌ Este comando solo se puede usar dentro de los canales de un juicio activo.")
        return

    datos = juicios_activos[category.id]
    guild = ctx.guild

    denunciante = guild.get_member(datos["denunciante"])
    acusado = guild.get_member(datos["acusado"])
    fiscal = guild.get_member(datos["abogado_fiscal"]) if datos["abogado_fiscal"] else None
    defensa = guild.get_member(datos["abogado_defensa"]) if datos["abogado_defensa"] else None

    votos = datos["votos_ganador"]
    v_acusador = sum(1 for v in votos.values() if v == "Acusador")
    v_acusado = sum(1 for v in votos.values() if v == "Acusado")

    if v_acusador > v_acusado:
        ganador_str = f"🏆 **{denunciante.mention if denunciante else 'El Acusador'}** (Acusador)"
    elif v_acusado > v_acusador:
        ganador_str = f"🏆 **{acusado.mention if acusado else 'El Acusado'}** (Acusado)"
    elif v_acusador == 0 and v_acusado == 0:
        ganador_str = "🤝 Empate (Sin votos registrados)"
    else:
        ganador_str = f"🤝 Empate ({v_acusador} vs {v_acusado} votos)"

    castigo_ganador = "Ninguno seleccionado"
    c_castigos_channel = guild.get_channel(datos["msg_castigos_channel_id"])
    if c_castigos_channel and datos["msg_castigos_id"] and datos["castigos"]:
        try:
            msg_castigos = await c_castigos_channel.fetch_message(datos["msg_castigos_id"])
            max_votos = -1
            i_ganador = -1

            for reaction in msg_castigos.reactions:
                if reaction.emoji in EMOJIS_NUMEROS:
                    idx = EMOJIS_NUMEROS.index(reaction.emoji)
                    count = reaction.count - 1
                    if count > max_votos and idx < len(datos["castigos"]):
                        max_votos = count
                        i_ganador = idx

            if i_ganador != -1 and max_votos > 0:
                c_data = datos["castigos"][i_ganador]
                castigo_ganador = f"\"{c_data['texto']}\" (Propuesto por {c_data['autor']} con {max_votos} voto/s)"
            elif datos["castigos"]:
                c_data = datos["castigos"][0]
                castigo_ganador = f"\"{c_data['texto']}\" (Primer castigo propuesto)"
        except Exception as e:
            castigo_ganador = "Error al procesar los votos de castigos"

    embed = discord.Embed(
        title="⚖️ SENTENCIA FIRME DEL TRIBUNAL 📜",
        description="El juicio ha llegado a su fin. Registro oficial de la sesión:",
        color=discord.Color.red()
    )

    embed.add_field(
        name="🚨 Bandos Enfrentados",
        value=(
            f"• **Acusador:** {denunciante.mention if denunciante else 'Desconocido'}\n"
            f"  └ *Fiscal:* {fiscal.mention if fiscal else 'Ninguno'}\n\n"
            f"• **Acusado:** {acusado.mention if acusado else 'Desconocido'}\n"
            f"  └ *Defensa:* {defensa.mention if defensa else 'Ninguno'}"
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 Veredicto de la Comunidad",
        value=ganador_str,
        inline=False
    )

    embed.add_field(
        name="🔨 Castigo Impuesto",
        value=f"*{castigo_ganador}*",
        inline=False
    )

    embed.set_footer(text="La sesión ha sido clausurada. Los canales se eliminarán en unos segundos.")

    await ctx.send("⚖️ Emitiendo sentencia final... Este juicio se eliminará en 5 segundos.")
    
    canal_general = discord.utils.get(guild.text_channels, name="general")
    if canal_general:
        await canal_general.send(embed=embed)
    else:
        await ctx.send(embed=embed)

    await asyncio.sleep(5)

    for channel in category.channels:
        await channel.delete()
    await category.delete()

    del juicios_activos[category.id]


# ---------------------------------------------------------
# COMANDO DE AYUDA: !leyes
# ---------------------------------------------------------
@bot.command(name="leyes", aliases=["ayuda", "comandos"])
async def leyes(ctx):
    await ctx.send(embed=obtener_embed_leyes())


@bot.event
async def on_ready():
    print(f"¡Tribunal en sesión! Conectado como: {bot.user}")

bot.run(TOKEN)