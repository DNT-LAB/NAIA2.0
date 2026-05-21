"use strict";

const fs = require("fs");
const path = require("path");

exports.default = async function afterPack(context) {
  const userDataDir = path.join(context.appOutDir, "user-data");
  fs.mkdirSync(userDataDir, { recursive: true });
};
