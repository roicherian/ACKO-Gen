// ACKO Gen — Figma plugin main thread.
// Owns every figma.* call. All network requests happen in ui.html (the UI
// iframe) since that's the reliably-supported context for fetch() across
// Figma versions — this file only ever receives finished results (an image's
// bytes) or storage requests from the UI and turns them into canvas nodes.

const PANEL_WIDTH = 380;
const PANEL_HEIGHT = 640;

figma.showUI(__html__, { width: PANEL_WIDTH, height: PANEL_HEIGHT });

// Keeps the plugin discoverable from the toolbar with nothing selected.
figma.root.setRelaunchData({ open: "" });

function ratioToSize(ratioLabel) {
  const [w, h] = String(ratioLabel || "16:9").split(":").map(Number);
  const ratio = w && h ? w / h : 16 / 9;
  const baseWidth = 960;
  return { width: baseWidth, height: Math.round(baseWidth / ratio) };
}

function base64ToUint8Array(base64) {
  const binary = figma.base64Decode(base64);
  return binary;
}

async function insertGeneratedImage(base64, ratioLabel, promptText) {
  const bytes = base64ToUint8Array(base64);
  const image = figma.createImage(bytes);
  const { width, height } = ratioToSize(ratioLabel);

  const rect = figma.createRectangle();
  rect.resize(width, height);
  rect.fills = [{ type: "IMAGE", scaleMode: "FILL", imageHash: image.hash }];
  rect.name = promptText ? `ACKO Gen: ${promptText.slice(0, 60)}` : "ACKO Gen image";

  // Place near the viewport center rather than the page origin, so it lands
  // where the user is actually looking.
  const center = figma.viewport.center;
  rect.x = Math.round(center.x - width / 2);
  rect.y = Math.round(center.y - height / 2);

  figma.currentPage.appendChild(rect);
  figma.currentPage.selection = [rect];
  figma.viewport.scrollAndZoomIntoView([rect]);
  rect.setRelaunchData({ open: "" });

  return { width, height };
}

figma.ui.onmessage = async (message) => {
  try {
    if (message.type === "resize") {
      figma.ui.resize(
        PANEL_WIDTH,
        Math.max(400, Math.min(900, Math.round(message.height)))
      );
      return;
    }

    if (message.type === "request-token") {
      const token = await figma.clientStorage.getAsync("acko_pat");
      figma.ui.postMessage({ type: "token", token: token || "" });
      return;
    }

    if (message.type === "save-token") {
      await figma.clientStorage.setAsync("acko_pat", message.token || "");
      figma.ui.postMessage({ type: "token-saved" });
      return;
    }

    if (message.type === "insert-image") {
      const { width, height } = await insertGeneratedImage(
        message.base64,
        message.ratio,
        message.prompt
      );
      figma.ui.postMessage({ type: "inserted", width, height });
      return;
    }
  } catch (err) {
    figma.ui.postMessage({
      type: "error",
      message: err && err.message ? err.message : String(err),
    });
  }
};
