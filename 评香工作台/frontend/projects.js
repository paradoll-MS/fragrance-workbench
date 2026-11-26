const KIND_LABELS = { customer: "客户委托", internal_upgrade: "内部升级", invent: "主动开发" };

async function createProject() {
  const meta = await boot();
  const name = textInput("", "例如：2026 春季洗护香精推荐");
  const customer = textInput("", "客户或委托方，可留空");
  const code = textInput("", "项目编号，可留空");
  const kind = selectInput(meta.project_kinds.map(item => ({ value: item.value, label: item.label })), "customer");
  const save = h("button", { class: "btn primary", text: "建立项目" });
  const box = dialog("新建项目", [
    field("项目名称", name), field("委托方", customer),
    h("div", { class: "grid2" }, field("项目类型", kind), field("项目编号", code)),
  ], [h("button", { class: "btn", text: "取消", onclick: () => box.close() }), save]);
  save.addEventListener("click", () => run(save, async () => {
    if (!name.value.trim()) throw new Error("请填写项目名称");
    const created = await post("/api/projects", { name: name.value, kind: kind.value, customer: customer.value, code: code.value });
    box.close();
    location.href = "/project.html?id=" + created.project_id;
  }));
}

function projectRow(project) {
  return h("div", { class: "item" },
    h("div", { class: "row between" },
      h("div", { class: "row" },
        h("a", { href: "/project.html?id=" + project.id, text: project.name, class: "slot-head id" }),
        chip(KIND_LABELS[project.kind] || project.kind, "plain"),
        project.customer ? h("span", { class: "muted small", text: project.customer }) : null),
      h("div", { class: "row" },
        chip(project.slot_done + "/" + project.slot_count + " 目标位"),
        project.issue_count ? chip(project.issue_count + " 项待处理", "warn") : chip("无待处理", "ok"))),
    h("div", { class: "muted small", text: "更新于 " + fmtDate(project.updated_at) + " · 子项 " + project.subproject_count + " · 已完成 " + project.subproject_done }),
  );
}

async function main() {
  const app = $("#app");
  app.append(nav("projects"));
  const button = h("button", { class: "btn", text: "新建项目" });
  app.append(h("div", { class: "row between" },
    h("div", {}, h("h1", { text: "项目" }), h("div", { class: "sub", text: "一次委托或一次开发就是一个项目；一个项目可以拆成多个交付方向。" })),
    button));
  button.addEventListener("click", () => run(button, createProject));
  const list = h("div", { class: "list" });
  app.append(h("div", { class: "section" }, list));
  const data = await get("/api/projects");
  if (!data.projects.length) {
    list.append(h("div", { class: "card soft" },
      h("div", { text: "还没有项目。" }),
      h("div", { class: "muted small", text: "点右上角新建，然后把第一份客户资料读进来。" })));
    return;
  }
  for (const project of data.projects) list.append(projectRow(project));
}

main().catch(error => toast(error.message));
