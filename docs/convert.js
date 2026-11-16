// Animated WebP to video or GIF, inside the browser: the files never leave the device.
// The browser decodes the WebP (ImageDecoder) and encodes video (WebCodecs);
// Mediabunny drives the encoder and writes the container, gifenc writes GIF.
import {BufferTarget, Mp4OutputFormat, Output, Quality, VideoSample, VideoSampleSource, WebMOutputFormat}
  from 'https://cdn.jsdelivr.net/npm/mediabunny@1.65.0/dist/bundles/mediabunny.min.mjs';
import {GIFEncoder, applyPalette, quantize}
  from 'https://cdn.jsdelivr.net/npm/gifenc@1.0.3/dist/gifenc.esm.js';

// Quality levels, measured to land near the desktop app's CRF 18, 22 and 26.
const FORMATS = {
  // quantizer: the H.264 quality step. rate: for an encoder that cannot hold a quality
  // step, a bitrate in bits per pixel per second. Chrome's own H.264 encoder is such a
  // one; it serves where there is no hardware encoder, and for frames narrower than 146
  // or lower than 50. It gets half as much again as those CRFs spent on a busy clip,
  // which is what it needed to look the same.
  mp4: {codec: 'avc', Format: Mp4OutputFormat, quality: {
    best: {quantizer: 22, rate: 21}, good: {quantizer: 25, rate: 8}, small: {quantizer: 30, rate: 2.5},
  }},
  // VP9's quality steps changed scale between Chrome versions; Mediabunny's levels follow that.
  webm: {codec: 'vp9', Format: WebMOutputFormat, quality: {best: 1.2, good: 1.1, small: 0.95}},
};

// Boxes a frame is fitted into, keeping its shape: the desktop app's presets.
const SIZES = {'480p': [854, 480], '720p': [1280, 720], '1080p': [1920, 1080], '4k': [3840, 2160]};

// A frame that stores no duration lasts one frame at 16 fps, the desktop app's default.
export const FALLBACK_MICROSECONDS = 1e6 / 16;

export const supported = () => 'ImageDecoder' in self && 'VideoEncoder' in self;

// The even number nearest to x that is no more than limit: H.264 needs even dimensions.
function evenWithin(x, limit) {
  x = Math.max(2, Math.min(x, limit));
  if (x % 2) x += x + 1 <= limit ? 1 : -1;
  return Math.max(2, x);
}

// The largest even size inside a box that keeps the shape of w x h (the desktop app's fit_box).
function fitBox(w, h, boxW, boxH) {
  const ratio = Math.min(boxW / w, boxH / h);
  return [evenWithin(Math.round(w * ratio), boxW), evenWithin(Math.round(h * ratio), boxH)];
}

// Draw a frame into the canvas, centred and keeping its shape. Bars are black, as in
// the desktop app, and so is whatever shows through a see-through frame; only a GIF
// frame that needs no bars keeps its transparency.
// Every frame goes through the canvas, also one that already has the output size:
// it costs no time, flattens transparency the same way for every file, and gives
// video the limited colour range that every player expects.
function fit(context, image, keepAlpha) {
  const {width, height} = context.canvas;
  const [w, h] = fitBox(image.displayWidth, image.displayHeight, width, height);
  if (keepAlpha && w === width && h === height) context.clearRect(0, 0, width, height);
  else context.fillRect(0, 0, width, height);       // the fill colour starts out black
  context.drawImage(image, (width - w) / 2, (height - h) / 2, w, h);
}

// Both encoders take frames with add(frame, microseconds, microseconds), give the
// file with finish(), and release what they hold with cancel().

async function videoEncoder({codec, Format, quality: levels}, quality, pixels, encoding) {
  const level = levels[quality] ?? quality;
  const output = new Output({format: new Format(), target: new BufferTarget()});
  const source = new VideoSampleSource({
    codec,
    quality: new Quality(level.rate ? {quantizer: level.quantizer, bitrate: Math.round(level.rate * pixels)} : level),
    ...encoding,
  });
  output.addVideoTrack(source);
  await output.start();
  return {
    async add(frame, time, duration) {
      const sample = new VideoSample(frame, {timestamp: time / 1e6, duration: duration / 1e6});
      try {
        await source.add(sample);
      } finally {
        sample.close();
      }
    },
    async finish() {
      await output.finalize();
      return new Blob([output.target.buffer], {type: output.format.mimeType});
    },
    cancel: () => output.cancel(),
  };
}

function gifEncoder() {
  const gif = GIFEncoder();
  return {
    // shortcut: colours are reduced on the page's own thread, move it to a worker if big GIFs make the page stutter
    add(canvas, _time, duration) {
      const {width, height} = canvas;
      const rgba = canvas.getContext('2d').getImageData(0, 0, width, height).data;
      // As the desktop app does: 255 colours, and one more index for see-through pixels.
      const palette = quantize(rgba, 255);
      const index = applyPalette(rgba, palette);
      const hole = palette.length;
      let transparent = false;
      for (let i = 0; i < index.length; i++) {
        if (rgba[i * 4 + 3] <= 128) {
          index[i] = hole;
          transparent = true;
        }
      }
      if (transparent) palette.push([0, 0, 0]);
      // Browsers slow down a frame shorter than 20 ms, so no frame is given less.
      gif.writeFrame(index, width, height, {
        palette, transparent, transparentIndex: hole, dispose: 2, delay: Math.max(20, duration / 1000),
      });
    },
    finish() {
      gif.finish();
      return new Blob([gif.bytes()], {type: 'image/gif'});
    },
    cancel() {},
  };
}

/**
 * Convert WebP Files, one after the other, to a single video or GIF Blob.
 *
 * format   'mp4', 'webm' or 'gif'
 * quality  'best', 'good' or 'small', or anything Mediabunny's Quality accepts
 * size     'same', or a key of SIZES; the first file sets the output size and
 *          the others are fitted into it
 * fps      a frame rate for every frame; without it each frame keeps its own duration
 * signal   an AbortSignal that stops the conversion
 * onProgress gets 0..1. Other options go to the video encoder as they are.
 */
export async function convert(files, {
  format = 'mp4', quality = 'good', size = 'same', fps, signal, onProgress, ...encoding
} = {}) {
  const gif = format === 'gif';
  let encoder, context, time = 0;
  try {
    for (const [n, file] of files.entries()) {
      const decoder = new ImageDecoder({data: file.stream(), type: 'image/webp'});
      try {
        // The frame count is final only once the whole file has been read.
        await Promise.all([decoder.tracks.ready, decoder.completed]);
        const count = decoder.tracks.selectedTrack.frameCount;
        for (let i = 0; i < count; i++) {
          signal?.throwIfAborted();
          const {image} = await decoder.decode({frameIndex: i});
          try {
            const {displayWidth: w, displayHeight: h} = image;
            if (!context) {
              // The first frame gives the output its size, and with it the encoder its settings.
              const [width, height] = SIZES[size] ? fitBox(w, h, ...SIZES[size]) : [w + w % 2, h + h % 2];
              context = new OffscreenCanvas(width, height).getContext('2d', {willReadFrequently: gif});
              context.imageSmoothingQuality = 'high';
              encoder = gif ? gifEncoder() : await videoEncoder(FORMATS[format], quality, width * height, encoding);
            }
            fit(context, image, gif);
            const duration = fps ? 1e6 / fps : image.duration || FALLBACK_MICROSECONDS;
            await encoder.add(context.canvas, time, duration);
            time += duration;
          } finally {
            image.close();
          }
          onProgress?.((n + (i + 1) / count) / files.length);
        }
      } catch (error) {
        // Say which of several combined files failed.
        throw files.length > 1 ? new Error(`${file.name}: ${error.message}`, {cause: error}) : error;
      } finally {
        decoder.close();
      }
    }
    return await encoder.finish();
  } catch (error) {
    await encoder?.cancel();            // there is none yet if the first file would not open
    throw error;
  }
}
