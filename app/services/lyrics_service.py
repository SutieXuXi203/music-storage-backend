import re
import json
import time
import urllib.request
import urllib.parse
from typing import Optional, Tuple, Dict, Any


def clean_title_and_artist(raw_title: str, raw_artist: Optional[str] = None) -> Tuple[str, str]:
    """
    Làm sạch tiêu đề và nghệ sĩ từ YouTube.
    Ví dụ:
    - 'Sơn Tùng M-TP | CHÚNG TA CỦA HIỆN TẠI | OFFICIAL MUSIC VIDEO' -> ('CHÚNG TA CỦA HIỆN TẠI', 'Sơn Tùng M-TP')
    - 'Wiz Khalifa - See You Again ft. Charlie Puth [Official Video] Furious 7 Soundtrack' -> ('See You Again', 'Wiz Khalifa')
    - 'MONO - Waiting For You (Album 22) [Official Audio]' -> ('Waiting For You', 'MONO')
    - 'Đen - Mang Tiền Về Cho Mẹ ft. Nguyên Thảo (M/V)' -> ('Mang Tiền Về Cho Mẹ', 'Đen')
    """
    artist = (raw_artist or "").strip()
    title = raw_title.strip()

    # 1. Bỏ các từ khóa rác đứng sau dấu gạch đứng hoặc gạch ngang (ví dụ: | OFFICIAL MUSIC VIDEO, - Official MV)
    keywords_clean = [
        r"(?:\||\-|\/)\s*(?:official\s*(?:music\s*)?video|official\s*mv|official\s*audio|music\s*video|lyric\s*video|mv\s*official|m\/v|mv|audio)\b.*$",
    ]
    for pattern in keywords_clean:
        title = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()

    # 2. Bỏ các thẻ trong ngoặc vuông [] hoặc tròn ()
    noise_brackets = [
        r"\[(official|audio|mv|m/v|video|music video|lyric|lyrics|karaoke|vietsub|hd|4k|remix|live|live performance|prod\.|produced by).*?\]",
        r"\((official|audio|mv|m/v|video|music video|lyric|lyrics|karaoke|vietsub|hd|4k|remix|live|live performance|album|prod\.|produced by).*?\)",
    ]
    for pattern in noise_brackets:
        title = re.sub(pattern, "", title, flags=re.IGNORECASE)

    # 3. Phân tách nếu có dấu ' - ' hoặc ' | '
    delimiters = [" | ", " - ", " – ", " — "]
    for delim in delimiters:
        if delim in title:
            parts = [p.strip() for p in title.split(delim) if p.strip()]
            if len(parts) >= 2:
                candidate_artist = parts[0]
                candidate_title = parts[1]
                title = candidate_title
                if not artist or artist.lower() == "unknown artist" or len(artist) > len(candidate_artist):
                    artist = candidate_artist
                elif candidate_artist.lower() in artist.lower():
                    artist = candidate_artist
                break

    # 4. Loại bỏ ft., feat.
    title = re.sub(r"\b(ft\.|feat\.|featuring)\s+.*", "", title, flags=re.IGNORECASE).strip()
    title = title.strip(" -|/[]()")

    # 5. Làm sạch artist
    artist = re.sub(r"(\s+-\s+Topic|\s+Official|\s+VEVO|\s+Channel)$", "", artist, flags=re.IGNORECASE).strip()
    artist = artist.strip(" -|/[]()")

    if not artist:
        artist = (raw_artist or "Unknown Artist").strip()

    return title, artist


def parse_vtt_to_lrc(vtt_text: str) -> Tuple[str, str]:
    """
    Chuyển đổi phụ đề WebVTT sang định dạng Synced Lyrics LRC ([mm:ss.xx] text)
    và Plain text lyrics. Giữ trọn vẹn các đoạn điệp khúc/lặp lại của bài hát.
    """
    lines = vtt_text.splitlines()
    lrc_lines = []
    plain_lines = []
    last_text = None
    last_time = None

    # Regex cho timestamp WebVTT: 00:01:23.456 hoặc 01:23.456
    time_regex = re.compile(r"(?:(\d{2}):)?(\d{2}):(\d{2})\.(\d{2,3})\s*-->")

    current_time = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE") or line.isdigit():
            continue

        match = time_regex.search(line)
        if match:
            hours = match.group(1)
            mins = int(match.group(2))
            secs = int(match.group(3))
            ms = match.group(4)
            if hours:
                mins += int(hours) * 60

            ms_str = ms[:2].ljust(2, "0")
            current_time = f"{mins:02d}:{secs:02d}.{ms_str}"
        elif current_time:
            clean_text = re.sub(r"<[^>]+>", "", line).strip()
            if clean_text:
                if clean_text != last_text or current_time != last_time:
                    lrc_lines.append(f"[{current_time}] {clean_text}")
                    plain_lines.append(clean_text)
                    last_text = clean_text
                    last_time = current_time
            current_time = None

    return "\n".join(plain_lines), "\n".join(lrc_lines)


class LyricsService:
    """Service tìm kiếm và trích xuất lời bài hát (LRCLIB & YouTube Captions)"""

    LRCLIB_BASE_URL = "https://lrclib.net/api"
    USER_AGENT = "MusicStorageApp/1.0 (https://github.com/manhd/music-app)"

    @classmethod
    def _fetch_json(cls, url: str, retries: int = 1) -> Optional[Any]:
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": cls.USER_AGENT, "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=7) as resp:
                    return json.loads(resp.read().decode("utf-8", errors="ignore"))
            except Exception as e:
                if attempt < retries:
                    time.sleep(0.5)
                continue
        return None

    @classmethod
    def fetch_from_lrclib(
        cls,
        title: str,
        artist: Optional[str] = None,
        duration: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Tìm kiếm lời bài hát từ LRCLIB:
        1. Thử endpoint /api/get (chính xác track_name + artist_name)
        2. Thử endpoint /api/search (tìm theo query và lọc kết quả tương đồng)
        """
        clean_t, clean_a = clean_title_and_artist(title, artist)

        # 1. Thử /api/get
        if clean_t and clean_a:
            params = {
                "track_name": clean_t,
                "artist_name": clean_a,
            }
            if duration and duration > 0:
                params["duration"] = str(duration)

            query_str = urllib.parse.urlencode(params)
            url = f"{cls.LRCLIB_BASE_URL}/get?{query_str}"
            data = cls._fetch_json(url)
            if data and (data.get("plainLyrics") or data.get("syncedLyrics")):
                return {
                    "lyrics": data.get("plainLyrics") or "",
                    "synced_lyrics": data.get("syncedLyrics") or "",
                    "source": "lrclib_exact",
                }

        # 2. Thử /api/search
        search_queries = [
            f"{clean_t} {clean_a}".strip(),
            clean_t,
        ]

        clean_t_lower = clean_t.lower()
        clean_a_lower = clean_a.lower()

        for sq in search_queries:
            if not sq:
                continue
            url = f"{cls.LRCLIB_BASE_URL}/search?q={urllib.parse.quote(sq)}"
            results = cls._fetch_json(url)
            if results and isinstance(results, list) and len(results) > 0:
                # Lọc bài hát phù hợp về tiêu đề hoặc ca sĩ
                matched_items = []
                for item in results:
                    track = (item.get("trackName") or "").lower()
                    art = (item.get("artistName") or "").lower()

                    t_match = clean_t_lower in track or track in clean_t_lower
                    a_match = clean_a_lower in art or art in clean_a_lower

                    if t_match or a_match:
                        matched_items.append(item)

                if matched_items:
                    # Ưu tiên bài có syncedLyrics trước
                    best = next((i for i in matched_items if i.get("syncedLyrics")), matched_items[0])
                    if best.get("syncedLyrics") or best.get("plainLyrics"):
                        return {
                            "lyrics": best.get("plainLyrics") or "",
                            "synced_lyrics": best.get("syncedLyrics") or "",
                            "source": "lrclib_search",
                        }

        return None

    @classmethod
    def fetch_from_youtube_info(cls, info: dict, only_manual: bool = False) -> Optional[Dict[str, Any]]:
        """
        Trích xuất lời bài hát từ phụ đề chính thức hoặc auto-captions của YouTube video.
        """
        if not info:
            return None

        subs = info.get("subtitles") or {}
        auto_subs = {} if only_manual else (info.get("automatic_captions") or {})

        target_lang_keys = ["vi", "en", "vi-VN", "en-US"]

        def find_vtt_url(caption_dict: dict) -> Optional[str]:
            for lang in target_lang_keys:
                for k, v in caption_dict.items():
                    if k.lower().startswith(lang):
                        for fmt in v:
                            if fmt.get("ext") == "vtt":
                                return fmt.get("url")
            for k, v in caption_dict.items():
                for fmt in v:
                    if fmt.get("ext") == "vtt":
                        return fmt.get("url")
            return None

        vtt_url = find_vtt_url(subs) or find_vtt_url(auto_subs)
        if not vtt_url:
            return None

        try:
            req = urllib.request.Request(vtt_url, headers={"User-Agent": cls.USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                vtt_text = resp.read().decode("utf-8", errors="ignore")
                plain, synced = parse_vtt_to_lrc(vtt_text)
                if plain or synced:
                    return {
                        "lyrics": plain,
                        "synced_lyrics": synced,
                        "source": "youtube_captions",
                    }
        except Exception as e:
            print(f"[LyricsService] Lỗi trích xuất phụ đề YouTube: {e}")

        return None

    @classmethod
    def fetch_from_youtube_search(cls, title: str, artist: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Tìm kiếm video YouTube để lấy phụ đề chính thức (manual subtitles) khớp với file âm thanh.
        """
        query = f"ytsearch1:{title} {artist or ''}".strip()
        try:
            import yt_dlp
            ydl_opts = {
                "skip_download": True,
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                if info and "entries" in info and len(info["entries"]) > 0:
                    entry = info["entries"][0]
                    return cls.fetch_from_youtube_info(entry, only_manual=True)
        except Exception as e:
            print(f"[LyricsService] Lỗi tìm kiếm phụ đề YouTube: {e}")
        return None

    @classmethod
    def get_lyrics(
        cls,
        title: str,
        artist: Optional[str] = None,
        duration: Optional[int] = None,
        video_info: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """
        Chiến lược trích xuất lời bài hát hoàn chỉnh:
        1. ƯU TIÊN 1: Phụ đề chính thức từ YouTube (khớp 100% thời lượng bài hát tải về, tránh lệch intro).
        2. ƯU TIÊN 2: LRCLIB (kho nhạc chuẩn phòng thu quốc tế & V-Pop).
        3. ƯU TIÊN 3: Phụ đề YouTube tự động (auto captions).
        """
        # 1. Thử phụ đề chính thức từ video_info nếu có sẵn
        if video_info and video_info.get("subtitles"):
            res_yt = cls.fetch_from_youtube_info(video_info, only_manual=True)
            if res_yt and (res_yt.get("synced_lyrics") or res_yt.get("lyrics")):
                return res_yt

        # 2. Thử phụ đề chính thức từ YouTube search nếu không có video_info
        if not video_info:
            res_search_yt = cls.fetch_from_youtube_search(title, artist)
            if res_search_yt and res_search_yt.get("synced_lyrics"):
                return res_search_yt

        # 3. Tra cứu trên LRCLIB
        res = cls.fetch_from_lrclib(title, artist, duration)
        if res and (res.get("synced_lyrics") or res.get("lyrics")):
            return res

        # 4. Fallback: Phụ đề tự động từ video_info
        if video_info:
            res_auto = cls.fetch_from_youtube_info(video_info, only_manual=False)
            if res_auto and (res_auto.get("synced_lyrics") or res_auto.get("lyrics")):
                return res_auto

        return {
            "lyrics": None,
            "synced_lyrics": None,
            "source": None,
        }


lyrics_service = LyricsService()
