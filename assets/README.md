# Channel Toolkit brand assets

- `channel-mark.svg`: scalable recreation of the red five-arm mark supplied in chat.
  The original image attachment was not available as a filesystem asset. This is
  a vector rendition, not the original raster file. Used in the header and favicon.
- `fonts/LinkSans-LinkSansVF.woff2` and `fonts/link-sans.css`: locally served
  Link Sans variable font copied from
  the user's local `LINKTREE MMONN/linktree/public/fonts` assets.
- `brand.css`: retained legacy theme. The current interface loads its font from
  `fonts/link-sans.css` and colors from `frontend/device.css`.
- `ui/ui.js` and `ui/ui.css`: compiled shadcn/React interface and responsive
  creator-studio design. Rebuild from `frontend/` using `npm.cmd run build`.

These assets are served through an explicit allowlist in `web.py`.
No third-party font service is required.
