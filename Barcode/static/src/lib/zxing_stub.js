// Stub for the ZXing library. 
// In a production environment, you would place the actual zxing.min.js file here
// or use a bundled NPM import via an Odoo JS wrapper.
window.ZXing = {
    BrowserMultiFormatReader: class {
        decodeFromVideoDevice(deviceId, videoElement, callback) {
            console.log("ZXing stub: decodeFromVideoDevice called", deviceId, videoElement);
        }
        reset() {
            console.log("ZXing stub: reset called");
        }
    }
};
