# coding-tunes

A Claude Code mod that plays a YouTube Music or Spotify playlist while Claude works, and pauses it whenever you are needed. The player sits in a Winamp-style pane: the app, the track, the playlist, the elapsed time, a spectrum, and previous, play, pause and next controls.

## Install

At the prompt of a terminal session:

```
/plugin install coding-tunes --marketplace ericfisherdev/ericfisherdev-plugins
```

Answer `y` to add the marketplace and pick a scope. Requires Claude Code 2.1.296 or later (function hooks), Linux and Python 3.

## Use

| Command | What it does |
| --- | --- |
| `/coding-tunes --player=ytmusic --list=<playlist id>` | Loads the playlist (`--player=spotify` for Spotify). An id or a link both work. |
| `/coding-tunes` | Asks for the player and the playlist. |
| `/coding-tunes --setup` | Saves the default player and playlist. For YouTube Music it offers a browser login, for Spotify it links your account. |
| `/coding-tunes --stop` | Stops the shared player and closes the pane. |

## When it plays

- It plays once a turn has run for **10 seconds**, and pauses when the turn ends.
- It pauses as soon as a **permission dialog** or a **question** (AskUserQuestion) needs you, and resumes once it is answered.
- **Shared across sessions.** Every Claude session on the machine drives one player. While any session waits on your input, the player stays paused and no other session can resume it, not even with its play button. The waiting session may press play itself.
- **Your buttons.** Pause lasts until the next turn starts; play lasts until the next turn ends. Previous and next skip at any time.
- Pane hotkeys, while the pane has focus: `z` previous, `x` play, `c` pause, `b` next.

## Players

### YouTube Music

Needs `mpv` and `yt-dlp` from your package manager (for example `sudo pacman -S mpv yt-dlp` on Arch, `sudo apt install mpv yt-dlp` on Debian or Ubuntu). One detached `mpv` plays for every session and quits when the last session ends. If the last session crashes instead of ending, `mpv` keeps playing until the next session starts and pauses it, or until `/coding-tunes --stop`.

Private playlists need a browser's YouTube login: run `/coding-tunes --setup`, choose YouTube Music, and pick the browser you are signed in with. Firefox-family browsers (Zen, Firefox, LibreWolf, Floorp) are found by their default profile; Chromium-family ones (Chrome, Brave, Chromium, Vivaldi, Edge, Opera) may ask you to unlock your keyring. Without a browser login only public playlists open, and a playlist YouTube refuses shows an error in the pane.

Streaming YouTube through `yt-dlp` may be against YouTube's Terms of Service.

### Spotify

Needs Spotify Premium (the Web API's playback controls require it), and a Spotify client open somewhere for the sound to come from.

1. Create an app at [developer.spotify.com](https://developer.spotify.com/dashboard) with the redirect URI `http://127.0.0.1:8898/callback`.
2. Run `/coding-tunes --setup`, choose Spotify, and paste the app's client id under "Other".
3. Sign in on the page that opens. The tokens are kept in the plugin's store.

## Where the pane sits

The pane docks at the top right, beside the transcript, in Claude Code's fullscreen layout at 110 columns or more. On the main-screen layout (`CLAUDE_CODE_NO_FLICKER=0`, and tmux by default) or a narrower terminal it sits above the prompt; `/coding-tunes` says which applies.

## Files it writes

- `$XDG_RUNTIME_DIR/coding-tunes/` (or `~/.cache/coding-tunes/` when `XDG_RUNTIME_DIR` is unset; never `/tmp`): one small record per session, the shared intent, and mpv's socket and lock. Under `$XDG_RUNTIME_DIR` it lives in memory and is gone after a reboot.
- The plugin store: defaults, recent playlists, the browser-login choice, and Spotify tokens.

## Development

```
claude plugin validate <folder>
claude plugin test <folder>
```

The tests in `tests/` drive the rules directly and the hooks through the engine, with a fake mpv, file system and clock.
