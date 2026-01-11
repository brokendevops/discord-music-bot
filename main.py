import discord
from discord.ext import commands
import yt_dlp
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
import subprocess
import shutil

# Bot yapılandırması
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id='4b256d9e326c4b699c27de65a4798a22',
    client_secret='1c98b7a7d8dd4ca2987057e1353e62c8'
))

# yt-dlp ayarları
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': 'in_playlist'
}

ffmpeg_options = {
    'before_options':
    '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -b:a 128k'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# Müzik kuyruğu
queues = {}


class YTDLSource(discord.PCMVolumeTransformer):

    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.thumbnail = data.get('thumbnail')
        self.duration = data.get('duration')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        print(f"🔍 from_url çağrıldı: {url}")
        loop = loop or asyncio.get_event_loop()

        try:
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(url, download=False))
            print(f"📦 yt-dlp data alındı")
        except Exception as e:
            print(f"yt-dlp hatası: {e}")
            return None

        if 'entries' in data:
            data = data['entries'][0]

        # Stream URL'ini al
        if stream:
            formats = data.get('formats', [])
            # En iyi ses formatını bul
            audio_format = None
            for f in formats:
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    audio_format = f
                    break

            if audio_format:
                filename = audio_format['url']
            else:
                filename = data['url']
        else:
            filename = ytdl.prepare_filename(data)

        ffmpeg_path = shutil.which('ffmpeg')
        if not ffmpeg_path:
            ffmpeg_path = 'C:/ffmpeg/bin/ffmpeg.exe'

        # FFmpeg'i pipe modunda çalıştır
        audio_source = discord.FFmpegPCMAudio(
            filename,
            executable=ffmpeg_path,
            stderr=subprocess.PIPE,
            before_options=
            '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            options='-vn -b:a 128k')

        return cls(audio_source, data=data)


def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]


def format_duration(seconds):
    if not seconds:
        return "Bilinmiyor"
    seconds = int(seconds)  # Float'ı int'e çevir
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


async def play_next(ctx):
    queue = get_queue(ctx.guild.id)

    if len(queue) > 0:
        url = queue.pop(0)
        await play_song(ctx, url)
    else:
        await asyncio.sleep(180)  # 3 dakika bekle
        if ctx.voice_client and not ctx.voice_client.is_playing():
            await ctx.voice_client.disconnect()


async def play_song(ctx, url):
    print(f"🎵 play_song çağrıldı! URL: {url}")
    try:
        player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
        print(f"✅ Player oluşturuldu: {player.title}")
        ctx.voice_client.play(
            player, after=lambda e: bot.loop.create_task(play_next(ctx)))
        print(f"🎶 play() çağrıldı!") 
        print(f"🔊 voice_client.is_playing(): {ctx.voice_client.is_playing()}")  

        # Kaynak belirleme
        source = "🔴 YouTube"
        if 'spotify' in url.lower():
            source = "🟢 Spotify"

        embed = discord.Embed(title=f"{source} Müzik Çalıyor",
                              description=f"[{player.title}]({url})",
                              color=discord.Color.green() if source
                              == "🟢 Spotify" else discord.Color.red())
        embed.add_field(name="Süre", value=format_duration(player.duration))
        if player.thumbnail:
            embed.set_thumbnail(url=player.thumbnail)

        await ctx.send(embed=embed)
    except Exception as e:
        print(f"Oynatma hatası: {e}")
        await ctx.send(
            "Şarkı oynatılırken bir hata oluştu, sonrakine geçiliyor...")
        await play_next(ctx)


def is_spotify_url(url):
    return 'spotify.com' in url


async def get_spotify_track_info(track_id):
    try:
        track = spotify.track(track_id)
        query = f"{track['name']} {track['artists'][0]['name']}"
        return query
    except Exception as e:
        print(f"Spotify hatası: {e}")
        return None


async def get_spotify_playlist_tracks(playlist_id):
    try:
        results = spotify.playlist_tracks(playlist_id)
        tracks = []
        for item in results['items'][:50]:  # İlk 50 şarkı
            track = item['track']
            query = f"{track['name']} {track['artists'][0]['name']}"
            tracks.append(query)
        return tracks
    except Exception as e:
        print(f"Spotify playlist hatası: {e}")
        return []


async def get_spotify_album_tracks(album_id):
    try:
        results = spotify.album_tracks(album_id)
        album = spotify.album(album_id)
        tracks = []
        for item in results['items']:
            query = f"{item['name']} {album['artists'][0]['name']}"
            tracks.append(query)
        return tracks
    except Exception as e:
        print(f"Spotify album hatası: {e}")
        return []


@bot.event
async def on_ready():
    print(f'Bot hazır! {bot.user} olarak giriş yapıldı.')


@bot.command(name='play', aliases=['p'])
async def play(ctx, *, query):
    """Müzik çalar - YouTube linki, Spotify linki veya şarkı adı"""

    voice_channel = ctx.author.voice.channel if ctx.author.voice else None

    if not voice_channel:
        await ctx.send("Müzik çalmak için bir ses kanalında olmalısın! 🎵")
        return

    if not ctx.voice_client:
        await voice_channel.connect()

    # Spotify URL kontrolü
    if is_spotify_url(query):
        loading_msg = await ctx.send("🔍 Spotify'dan bilgiler alınıyor...")

        if 'track' in query:
            track_id = query.split('track/')[-1].split('?')[0]
            search_query = await get_spotify_track_info(track_id)
            if search_query:
                query = search_query
            await loading_msg.delete()

        elif 'playlist' in query:
            playlist_id = query.split('playlist/')[-1].split('?')[0]
            tracks = await get_spotify_playlist_tracks(playlist_id)
            if tracks:
                await loading_msg.edit(
                    content=f"📝 {len(tracks)} şarkı kuyruğa ekleniyor...")
                for i, track in enumerate(tracks):
                    if i == 0 and not ctx.voice_client.is_playing():
                        await play_song(ctx, track)
                    else:
                        get_queue(ctx.guild.id).append(track)
                await loading_msg.edit(
                    content=f"✅ {len(tracks)} şarkı kuyruğa eklendi!")
                return
            await loading_msg.delete()

        elif 'album' in query:
            album_id = query.split('album/')[-1].split('?')[0]
            tracks = await get_spotify_album_tracks(album_id)
            if tracks:
                await loading_msg.edit(
                    content=f"📀 {len(tracks)} şarkı kuyruğa ekleniyor...")
                for i, track in enumerate(tracks):
                    if i == 0 and not ctx.voice_client.is_playing():
                        await play_song(ctx, track)
                    else:
                        get_queue(ctx.guild.id).append(track)
                await loading_msg.edit(
                    content=f"✅ {len(tracks)} şarkı kuyruğa eklendi!")
                return
            await loading_msg.delete()

    # Şarkı çal veya kuyruğa ekle
    if ctx.voice_client.is_playing():
        get_queue(ctx.guild.id).append(query)

        embed = discord.Embed(title="✅ Kuyruğa Eklendi",
                              description=f"Şarkı kuyruğa eklendi",
                              color=discord.Color.green())
        embed.add_field(name="Sıra", value=f"{len(get_queue(ctx.guild.id))}")
        await ctx.send(embed=embed)
    else:
        await play_song(ctx, query)


@bot.command(name='skip', aliases=['s'])
async def skip(ctx):
    """Şarkıyı geçer"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.message.add_reaction('⏭️')
    else:
        await ctx.send("Şu anda çalan şarkı yok!")


@bot.command(name='stop')
async def stop(ctx):
    """Müziği durdurur ve botuyu ses kanalından çıkarır"""
    if ctx.voice_client:
        get_queue(ctx.guild.id).clear()
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.message.add_reaction('⏹️')
    else:
        await ctx.send("Bot ses kanalında değil!")


@bot.command(name='pause')
async def pause(ctx):
    """Müziği duraklatır"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.message.add_reaction('⏸️')
    else:
        await ctx.send("Şu anda çalan şarkı yok!")


@bot.command(name='resume')
async def resume(ctx):
    """Müziği devam ettirir"""
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.message.add_reaction('▶️')
    else:
        await ctx.send("Müzik zaten çalıyor veya duraklatılmış şarkı yok!")


@bot.command(name='queue', aliases=['q'])
async def queue(ctx):
    """Müzik kuyruğunu gösterir"""
    queue_list = get_queue(ctx.guild.id)

    if not queue_list:
        await ctx.send("Kuyruk boş! 📭")
        return

    embed = discord.Embed(title="🎵 Müzik Kuyruğu", color=discord.Color.blue())

    queue_text = "\n".join(
        [f"**{i+1}.** {song}" for i, song in enumerate(queue_list[:10])])
    embed.description = queue_text
    embed.set_footer(text=f"Toplam {len(queue_list)} şarkı")

    await ctx.send(embed=embed)


@bot.command(name='np', aliases=['nowplaying'])
async def now_playing(ctx):
    """Şu anda çalan şarkıyı gösterir"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        source = ctx.voice_client.source
        embed = discord.Embed(title="🎵 Şu Anda Çalıyor",
                              description=f"[{source.title}]({source.url})",
                              color=discord.Color.blue())
        embed.add_field(name="Süre", value=format_duration(source.duration))
        if source.thumbnail:
            embed.set_thumbnail(url=source.thumbnail)
        await ctx.send(embed=embed)
    else:
        await ctx.send("Şu anda çalan şarkı yok!")


@bot.command(name='muzik', aliases=['commands'])
async def help_command(ctx):
    """Yardım menüsünü gösterir"""
    embed = discord.Embed(
        title="🎵 Müzik Botu Komutları",
        description="Spotify ve YouTube desteği ile müzik dinle!",
        color=discord.Color.gold())
    embed.add_field(name="!play <şarkı/link>",
                    value="YouTube veya Spotify'dan şarkı çalar (kısaca: !p)",
                    inline=False)
    embed.add_field(name="🟢 Spotify Desteği",
                    value="Şarkı, playlist ve albüm linkleri kullanabilirsin!",
                    inline=False)
    embed.add_field(name="!skip",
                    value="Şarkıyı geçer (kısaca: !s)",
                    inline=False)
    embed.add_field(name="!stop",
                    value="Müziği durdurur ve botuyu ses kanalından çıkarır",
                    inline=False)
    embed.add_field(name="!pause", value="Müziği duraklatır", inline=False)
    embed.add_field(name="!resume", value="Müziği devam ettirir", inline=False)
    embed.add_field(name="!queue",
                    value="Müzik kuyruğunu gösterir (kısaca: !q)",
                    inline=False)
    embed.add_field(name="!np",
                    value="Şu anda çalan şarkıyı gösterir",
                    inline=False)
    embed.add_field(name="!muzik",
                    value="Bu yardım menüsünü gösterir (kısaca: !commands)",
                    inline=False)
    embed.set_footer(text="🟢 Spotify | 🔴 YouTube")

    await ctx.send(embed=embed)


# Botu çalıştır
bot.run('MTQ1OTYyMzUzNTg4NTY4MDY0MA.GJT08m.8-i0QBg2aQiGjSFk_BTV6_-jwOCiIvNjxFvpKs')
