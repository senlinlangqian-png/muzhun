"use strict";
window.MuzhunUI = {
  upload(url, body, token, onProgress) {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", url); request.setRequestHeader("X-Muzhun-Token", token);
      request.upload.addEventListener("progress", event => { if (event.lengthComputable) onProgress(event.loaded / event.total); });
      request.addEventListener("load", () => {
        let data; try { data = JSON.parse(request.responseText); } catch { return reject(new Error("上传响应无法读取，请检查本地服务")); }
        if (request.status >= 200 && request.status < 300) resolve(data);
        else reject(new Error(typeof data.detail === "string" ? data.detail : "上传失败，请检查文件"));
      });
      request.addEventListener("error", () => reject(new Error("上传中断，请确认幕准仍在运行后重试")));
      request.addEventListener("abort", () => reject(new Error("上传已取消")));
      request.send(body);
    });
  }
};
