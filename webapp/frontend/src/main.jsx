import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { authorizationHeaders, resolveApiToken, tokenizedUrl } from './apiSecurity.js'
import { jobIdFromSearch, jobSelectionPath } from './jobLocation.js'
import { disposeThreeRenderer, disposeThreeScene, viewerFailureMessage } from './viewerResources.js'

const API = '/api'
let storedApiToken = ''
try { storedApiToken = window.sessionStorage.getItem('worldclaw_api_token') || '' } catch { /* unavailable in hardened browsers */ }
const API_TOKEN = resolveApiToken(window.location.search, storedApiToken)
if (API_TOKEN) {
  try { window.sessionStorage.setItem('worldclaw_api_token', API_TOKEN) } catch { /* keep the in-memory token */ }
}
const stageNames = {
  instantiate: '实例化场景契约', quality_gates: '四级质量审核',
  plan: '世界规划', prepare_assets: '准备资产', segment: 'SAM3 分割', review: '掩码审核',
  sam3d: 'SAM 3D Objects 审计', hunyuan_shape: 'Hunyuan3D 几何',
  hunyuan_paint: 'Hunyuan3D PBR', build: 'Blender 构建与渲染', validate: '质量验证', package: '交付打包',
  regional_plan: '冻结区域规划', regional_render: '区域基础渲染', regional_composition: '目标合成图',
  regional_segment: 'SAM3 区域分割', regional_sam3d: 'SAM 3D Objects 姿态',
  regional_hunyuan_shape: 'Hunyuan3D 高精几何', regional_hunyuan_paint: '9-view PBR 纹理',
  regional_refine: '三维回置与反馈校正', regional_validate: '论文链路验收'
}
const workflowNames = { template: '冻结模板派生', existing: '现有高质量资产', full: '完整论文级流程', denver_regional: '丹佛机场区域复现' }
const stateNames = {
  created: '待启动', queued: '排队中', running: '生成中', awaiting_review: '等待审核',
  contract_review: '契约审核中', succeeded: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断'
}

// The Studio intentionally owns at most one live browser renderer. React normally
// runs an effect cleanup before its replacement, and this lease also protects
// against future layouts accidentally mounting two heavyweight viewers at once.
let activeViewerRelease = null

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: authorizationHeaders(API_TOKEN, options.headers),
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try { message = (await response.json()).detail || message } catch { /* ignore */ }
    throw new Error(message)
  }
  if (response.status === 204) return null
  return response.json()
}

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = units[0]
  for (let i = 1; i < units.length && value >= 1024; i += 1) { value /= 1024; unit = units[i] }
  return `${value.toFixed(value > 10 ? 1 : 2)} ${unit}`
}

function StageRail({ stages = [] }) {
  return <div className="stage-rail">
    {stages.map((stage) => <div className={`stage ${stage.state}`} key={stage.name}>
      <span className="stage-dot">{stage.state === 'succeeded' ? '✓' : stage.position + 1}</span>
      <div><strong>{stageNames[stage.name] || stage.name}</strong><small>{stage.message || stage.state}</small></div>
    </div>)}
  </div>
}

function OrbitFallback({ frames = [], posterUrl, reason, onRetry }) {
  const sources = frames.length ? frames : (posterUrl ? [{ url: posterUrl, path: 'render' }] : [])
  const [index, setIndex] = useState(0)
  const drag = useRef(null)
  const sourceKey = sources.map(source => `${source.path || ''}:${source.url}`).join('|')
  const currentUrl = sources[index % Math.max(sources.length, 1)]?.url
  const nextUrl = sources[(index + 1) % Math.max(sources.length, 1)]?.url
  useEffect(() => setIndex(0), [sourceKey])
  useEffect(() => {
    // Keep the fallback lightweight: decode only the visible and adjacent frame,
    // rather than all 4K views immediately after a GPU allocation failure.
    ;[currentUrl, nextUrl].filter(Boolean).forEach(url => { const preload = new Image(); preload.src = url })
  }, [currentUrl, nextUrl])
  const move = (event) => {
    if (!drag.current || sources.length < 2) return
    const delta = event.clientX - drag.current.x
    const steps = Math.trunc(delta / 18)
    if (!steps) return
    setIndex(old => (old - steps + sources.length * 100) % sources.length)
    drag.current.x += steps * 18
  }
  return <div className="orbit-fallback">
    {sources.length > 0
      ? <img src={sources[index % sources.length].url} draggable="false" decoding="async" alt="场景静态多视角预览"
          onPointerDown={event => { drag.current = { x: event.clientX }; event.currentTarget.setPointerCapture(event.pointerId) }}
          onPointerMove={move} onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }} />
      : <div className="orbit-empty">暂无兼容预览帧</div>}
    <div className="orbit-badge"><strong>兼容预览</strong><span>{sources.length > 1 ? `左右拖拽旋转 · ${index + 1}/${sources.length}` : '高清渲染视图'}</span></div>
    <div className="orbit-error" role="alert"><strong>交互式 3D 暂不可用</strong><span>{reason || '已显示静态渲染预览，不影响 BLEND/GLB 下载。'}</span></div>
    <div className="orbit-actions"><span>静态渲染来自同一交付场景。</span><button onClick={onRetry}>释放其他 3D 页面后重试</button></div>
  </div>
}

function ThreeViewer({ url, bytes = 0, fallbackFrames = [], posterUrl }) {
  const canvasRef = useRef(null)
  const [enabled, setEnabled] = useState(false)
  const [phase, setPhase] = useState('idle')
  const [status, setStatus] = useState('')
  const [failure, setFailure] = useState('')
  const [attempt, setAttempt] = useState(0)
  const launch = () => {
    if (enabled) return
    setFailure(''); setStatus('正在准备低显存 3D 预览…'); setPhase('loading'); setEnabled(true); setAttempt(old => old + 1)
  }
  useEffect(() => {
    if (!enabled || !url || !canvasRef.current) return undefined
    const canvas = canvasRef.current
    const controller = new AbortController()
    let disposed = false; let released = false
    let renderer; let controls; let resize; let scene; let renderFrame; let contextLost
    const release = () => {
      if (released) return
      released = true
      disposed = true
      controller.abort()
      if (resize) window.removeEventListener('resize', resize)
      if (contextLost) canvas.removeEventListener('webglcontextlost', contextLost)
      if (controls && renderFrame) controls.removeEventListener('change', renderFrame)
      controls?.dispose()
      disposeThreeScene(scene)
      disposeThreeRenderer(renderer)
      scene = undefined
      renderer = undefined
      if (activeViewerRelease === release) activeViewerRelease = null
    }
    if (activeViewerRelease) activeViewerRelease()
    activeViewerRelease = release

    const useFallback = error => {
      if (disposed) return
      setFailure(viewerFailureMessage(error))
      setPhase('fallback')
      setEnabled(false)
      release()
    }
    const start = async () => {
      let THREE = await import('three')
      let backend = 'WebGL2'
      if (disposed) return
      let webglError
      try {
        // A low-memory context works on integrated GPUs and remote desktops
        // where the browser rejects the default high-quality context.
        renderer = new THREE.WebGLRenderer({
          canvas, antialias: false, alpha: false, stencil: false,
          powerPreference: 'low-power', failIfMajorPerformanceCaveat: false
        })
      } catch (error) {
        webglError = error
      }
      if (!renderer) {
        if (!navigator.gpu) throw webglError || new Error('WebGL2 context creation failed')
        try {
          THREE = await import('three/webgpu')
          renderer = new THREE.WebGPURenderer({ canvas, antialias: false, alpha: false, stencil: false })
          await renderer.init()
          backend = 'WebGPU'
        } catch (webgpuError) {
          disposeThreeRenderer(renderer)
          renderer = undefined
          throw new Error(`WebGL2 context: ${webglError?.message || 'unavailable'}; WebGPU context: ${webgpuError?.message || 'unavailable'}`)
        }
      }
      const [controlsModule, loaderModule, meshoptModule] = await Promise.all([
        import('three/examples/jsm/controls/OrbitControls.js'),
        import('three/examples/jsm/loaders/GLTFLoader.js'),
        import('three/examples/jsm/libs/meshopt_decoder.module.js')
      ])
      if (disposed) { disposeThreeRenderer(renderer); renderer = undefined; return }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25))
      renderer.outputColorSpace = THREE.SRGBColorSpace
      // Compress reconstruction highlights instead of clipping pale stone and
      // vertex-colour assets to white in the browser preview.
      renderer.toneMapping = THREE.ACESFilmicToneMapping
      renderer.toneMappingExposure = 0.95
      scene = new THREE.Scene()
      scene.background = new THREE.Color('#0c1713')
      const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 3000)
      camera.position.set(180, 130, 180)
      controls = new controlsModule.OrbitControls(camera, canvas)
      controls.enableDamping = false
      scene.add(new THREE.HemisphereLight(0xd8f5e7, 0x536057, 3.2))
      scene.add(new THREE.AmbientLight(0xffffff, 0.55))
      const sun = new THREE.DirectionalLight(0xffefd2, 2.0)
      sun.position.set(80, 160, 70); scene.add(sun)
      renderFrame = () => {
        if (disposed) return
        try {
          const result = renderer.renderAsync ? renderer.renderAsync(scene, camera) : renderer.render(scene, camera)
          result?.catch?.(useFallback)
        } catch (error) { useFallback(error) }
      }
      resize = () => {
        if (disposed) return
        const width = Math.max(canvas.clientWidth, 1); const height = Math.max(canvas.clientHeight, 1)
        renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix(); renderFrame()
      }
      controls.addEventListener('change', renderFrame)
      window.addEventListener('resize', resize)
      contextLost = event => { event.preventDefault(); useFallback(new Error('WebGL context lost because the browser reclaimed GPU resources')) }
      canvas.addEventListener('webglcontextlost', contextLost)
      setStatus(`正在通过 ${backend} 载入大型 GLB…`)
      const loader = new loaderModule.GLTFLoader()
      loader.setMeshoptDecoder(meshoptModule.MeshoptDecoder)
      resize()
      const response = await fetch(url, { signal: controller.signal, credentials: 'same-origin' })
      if (disposed) return
      if (!response.ok) throw new Error(`GLB 请求失败：HTTP ${response.status}`)
      const contentLength = Number(response.headers.get('content-length') || 0)
      if (contentLength > 0) setStatus(`正在通过 ${backend} 下载 ${formatBytes(contentLength)} GLB…`)
      const data = await response.arrayBuffer()
      if (disposed) return
      setStatus(`正在通过 ${backend} 解析并上传 GLB…`)
      const absoluteUrl = new URL(url, window.location.href)
      const resourcePath = new URL('.', absoluteUrl).href
      const gltf = await loader.parseAsync(data, resourcePath)
      if (disposed) {
        disposeThreeScene(gltf.scene)
        return
      }
      scene.add(gltf.scene)
      const box = new THREE.Box3().setFromObject(gltf.scene)
      const center = box.getCenter(new THREE.Vector3())
      const size = Math.max(box.getSize(new THREE.Vector3()).length(), 1)
      controls.target.copy(center)
      camera.position.copy(center).add(new THREE.Vector3(size * .55, size * .38, size * .55))
      camera.near = Math.max(size / 10000, .01)
      camera.far = size * 10
      camera.updateProjectionMatrix()
      controls.update()
      renderFrame()
      if (disposed) return
      setPhase('ready')
      setStatus(`${backend} · 拖拽旋转 · 滚轮缩放`)
    }
    start().catch(error => {
      if (disposed || error?.name === 'AbortError') return
      useFallback(error)
    })
    return release
  }, [enabled, url, attempt])
  if (!url) return null
  return <div className="viewer">
    {phase === 'idle' && <button className="viewer-launch" onClick={launch}>
      <strong>打开交互式三维预览</strong><span>{bytes ? `${formatBytes(bytes)} GLB` : '大型 GLB'} · 按需加载以免占用浏览器内存</span>
    </button>}
    {phase === 'fallback' && <OrbitFallback frames={fallbackFrames} posterUrl={posterUrl} reason={failure} onRetry={launch} />}
    <canvas key={`${url}:${attempt}`} ref={canvasRef} className={enabled ? '' : 'hidden'} />
    {enabled && phase === 'loading' && <div className="viewer-loading" aria-live="polite">
      {posterUrl && <img src={posterUrl} alt="场景加载占位预览" decoding="async" />}
      <span>{status}</span>
    </div>}
    {enabled && <small aria-live="polite">{status}</small>}
  </div>
}

function TemplateCatalog({ catalog, onInstantiate, busy }) {
  if (!catalog?.templates?.length) return null
  return <div className="contract-catalog">
    <div className="catalog-heading"><div><span className="eyebrow">FROZEN CONTRACTS</span><h2>已沉淀场景模板</h2></div><small>{catalog.asset_registry?.approved || 0} 项已批准资产</small></div>
    <div className="template-grid">{catalog.templates.map(template => <article key={template.scene_id}>
      <div><strong>{template.display_name}</strong><span className={`contract-state ${template.quality_status}`}>{template.quality_status}</span></div>
      <p>{template.quality_profile} · {template.bounds_m?.join(' × ')} m</p>
      <div className="template-foot"><small>{Object.values(template.review_gates || {}).filter(gate => gate.status === 'approved').length}/4 质量门已批准</small><button type="button" disabled={Boolean(busy)} onClick={() => onInstantiate(template)}>{busy === template.scene_id ? '正在创建…' : '从模板创建'}</button></div>
    </article>)}</div>
  </div>
}

function NewJob({ defaults, catalog, onCreated }) {
  const [workflow, setWorkflow] = useState('existing')
  const [quality, setQuality] = useState('paper')
  const [name, setName] = useState('Greenwater Frontier')
  const [source, setSource] = useState(null)
  const [reviewMode, setReviewMode] = useState('manual')
  const [archive, setArchive] = useState(false)
  const [prompts, setPrompts] = useState(defaults?.prompts || {})
  const [busy, setBusy] = useState(false)
  const [templateBusy, setTemplateBusy] = useState('')
  const [error, setError] = useState('')
  const instantiate = async (template) => {
    setTemplateBusy(template.scene_id); setError('')
    try {
      const job = await request(`/templates/${template.scene_id}/instantiate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: `${template.display_name} · 工作副本`, materialize_artifacts: true })
      })
      await onCreated(job.id)
    } catch (err) { setError(err.message) } finally { setTemplateBusy('') }
  }
  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const data = new FormData()
      data.append('name', name); data.append('workflow', workflow); data.append('quality', quality)
      data.append('config_json', JSON.stringify({ review_mode: reviewMode, make_archive: archive, prompts }))
      if (source) data.append('source', source)
      const job = await request('/jobs', { method: 'POST', body: data })
      await request(`/jobs/${job.id}/start`, { method: 'POST' })
      onCreated(job.id)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <section className="new-job">
    <div className="eyebrow">LOCAL WORLD FACTORY</div>
    <h1>从参考图，到可漫游的<br/><em>高保真 3D 世界</em></h1>
    <p className="intro">SAM3 精细分割、SAM 3D Objects 几何审计、Hunyuan3D 2.1 PBR 资产与 Blender Cycles 场景构建，全部在本机串成可恢复流程。</p>
    <TemplateCatalog catalog={catalog} onInstantiate={instantiate} busy={templateBusy} />
    {error && <p className="error catalog-error">{error}</p>}
    <form onSubmit={submit}>
      <div className="choice-row">
        <label className={workflow === 'existing' ? 'choice selected' : 'choice'}>
          <input type="radio" value="existing" checked={workflow === 'existing'} onChange={e => setWorkflow(e.target.value)} />
          <b>现有高质量资产</b><span>直接复用已验收 PBR 资产，生成完整世界</span>
        </label>
        <label className={workflow === 'full' ? 'choice selected' : 'choice'}>
          <input type="radio" value="full" checked={workflow === 'full'} onChange={e => setWorkflow(e.target.value)} />
          <b>完整论文级流程</b><span>参考图分割、重建、纹理、世界生成全链路</span>
        </label>
        <label className={workflow === 'denver_regional' ? 'choice selected' : 'choice'}>
          <input type="radio" value="denver_regional" checked={workflow === 'denver_regional'} onChange={e => { setWorkflow(e.target.value); setQuality('paper'); setName('Denver Concourse B · WorldClaw') }} />
          <b>丹佛机场论文复现</b><span>冻结相机、ARFF 生成、姿态回置、碰撞/接地与反馈验收</span>
        </label>
      </div>
      <div className="form-grid">
        <label><span>任务名称</span><input value={name} onChange={e => setName(e.target.value)} required /></label>
        <label><span>质量档</span><select value={quality} disabled={workflow === 'denver_regional'} onChange={e => setQuality(e.target.value)}>
          <option value="paper">论文级 · 1080p / 64 spp / 9-view PBR</option>
          <option value="standard">标准 · 720p / 32 spp</option>
          <option value="preview">预览 · 540p / 16 spp</option>
        </select></label>
        {workflow === 'full' && <label className="wide upload"><span>资产参考图</span>
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => setSource(e.target.files[0])} required />
          <small>建议使用清晰、无遮挡、主体完整的资产拼图或参考图。</small>
        </label>}
        {workflow === 'denver_regional' && <label className="wide upload"><span>可选：自定义 ARFF 合成图</span>
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => setSource(e.target.files[0])} />
          <small>留空会使用已验收的丹佛固定合成图；上传时需保持 1536×1024 冻结相机和原场景背景。</small>
        </label>}
      </div>
      {workflow === 'full' && <details>
        <summary>分割提示词与审核设置</summary>
        <div className="prompt-grid">{Object.entries(prompts).map(([key, value]) => <label key={key}><span>{key}</span><input value={value} onChange={e => setPrompts({ ...prompts, [key]: e.target.value })} /></label>)}</div>
        <label className="inline"><input type="checkbox" checked={reviewMode === 'manual'} onChange={e => setReviewMode(e.target.checked ? 'manual' : 'auto')} /> SAM3 后暂停，由我选择最佳掩码</label>
      </details>}
      <label className="inline"><input type="checkbox" checked={archive} onChange={e => setArchive(e.target.checked)} /> 完成后打包 ZIP（大型 BLEND/GLB 会占用额外空间）</label>
      <button className="primary" disabled={busy}>{busy ? '正在创建…' : '创建并开始生成'}</button>
    </form>
  </section>
}

function QualityPanel({ quality, images, artifacts, job, onChanged }) {
  const [left, setLeft] = useState(0); const [right, setRight] = useState(1)
  const [evidence, setEvidence] = useState({}); const [busy, setBusy] = useState(''); const [error, setError] = useState('')
  useEffect(() => { setLeft(0); setRight(images.length > 1 ? 1 : 0) }, [images.length])
  const report = quality?.quality_report
  const spec = quality?.world_spec
  const gates = spec?.review_gates || {}
  const groups = report?.groups || {}
  const evidenceFiles = artifacts.filter(item => !/\.(blend|glb|zip)$/i.test(item.path) && item.path !== 'world/world_spec.json')
  useEffect(() => {
    if (!evidenceFiles.length) return
    const patterns = { reference: /reference|contact|prompt|render/i, graybox: /automatic_geometry|geometry|audit/i, materials: /contact|render|png|jpe?g/i, final: /validation|checksum|quality_report/i }
    const defaults = {}
    Object.keys(gates).forEach(name => { defaults[name] = (evidenceFiles.find(item => patterns[name]?.test(item.path)) || evidenceFiles[0])?.path || '' })
    setEvidence(old => ({ ...defaults, ...old }))
  }, [job?.id, evidenceFiles.length, Object.keys(gates).join(',')])
  const changeGate = async (name, status) => {
    setBusy(name); setError('')
    try {
      await request(`/jobs/${job.id}/gates/${name}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, evidence: status === 'approved' ? [evidence[name]] : [], reviewer: 'local-user', notes: `${status} in WorldClaw Studio` })
      })
      await onChanged()
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }
  const measure = async () => {
    setBusy('measure'); setError('')
    try { await request(`/jobs/${job.id}/measure`, { method: 'POST' }); await onChanged() }
    catch (err) { setError(err.message) } finally { setBusy('') }
  }
  return <div className="quality-stack">
    <div className="panel quality-summary">
      <div className="panel-title"><div><span className="eyebrow">CONTRACT / QA</span><h2>{spec?.display_name || '兼容质量报告'}</h2></div><span className={`status ${quality?.status === 'passed' ? 'succeeded' : 'failed'}`}>{quality?.status || 'missing'}</span></div>
      <p className="muted">{spec ? `${spec.version || ''} · ${spec.quality_profile} · ${spec.bounds.extent_m.join(' × ')} m` : '该旧任务尚未接入 v1 世界契约，以下显示原有 validation.json。'}</p>
      {quality?.editable_gates && <div className="contract-actions"><span>修订 {quality.revisions?.length || 0} 次 · 所有审核操作均保留快照</span>{quality.measurement_available && <button disabled={Boolean(busy)} onClick={measure}>{busy === 'measure' ? 'Blender 量测中…' : '重新量测几何'}</button>}</div>}
      {Object.keys(groups).length > 0 && <div className="qa-groups">{Object.entries(groups).map(([name, passed]) => <div className={passed ? 'passed' : 'failed'} key={name}><span>{passed ? '✓' : '×'}</span><strong>{name}</strong></div>)}</div>}
      {Object.keys(gates).length > 0 && <div className={`gate-grid ${quality?.editable_gates ? 'editable' : ''}`}>{Object.entries(gates).map(([name, gate]) => <article key={name} className={gate.status}><div className="gate-title"><strong>{name}</strong><span>{gate.status}</span></div><small>{gate.evidence?.length || 0} 项证据{gate.reviewer ? ` · ${gate.reviewer}` : ''}</small>{quality?.editable_gates && <><select value={evidence[name] || ''} onChange={event => setEvidence(old => ({ ...old, [name]: event.target.value }))}>{evidenceFiles.map(item => <option key={item.path} value={item.path}>{item.path.replace('world/', '')}</option>)}</select><div className="gate-actions"><button disabled={Boolean(busy) || !evidence[name]} onClick={() => changeGate(name, 'approved')}>批准</button><button className="reject" disabled={Boolean(busy)} onClick={() => changeGate(name, 'rejected')}>驳回</button></div></>}</article>)}</div>}
      {report?.quality_boundary && <p className="quality-boundary">{report.quality_boundary}</p>}
      {error && <p className="error">{error}</p>}
    </div>
    {images.length > 1 && <div className="panel"><h2>验证视图 A/B 对比</h2>
      <div className="compare-controls"><label>A<select value={left} onChange={event => setLeft(Number(event.target.value))}>{images.map((item, index) => <option value={index} key={item.path}>{item.path.split('/').pop()}</option>)}</select></label><label>B<select value={right} onChange={event => setRight(Number(event.target.value))}>{images.map((item, index) => <option value={index} key={item.path}>{item.path.split('/').pop()}</option>)}</select></label></div>
      <div className="compare-grid"><a href={images[left]?.url} target="_blank"><img src={images[left]?.url}/><span>A · {images[left]?.path.split('/').pop()}</span></a><a href={images[right]?.url} target="_blank"><img src={images[right]?.url}/><span>B · {images[right]?.path.split('/').pop()}</span></a></div>
    </div>}
  </div>
}

function ReviewPanel({ job, onApproved }) {
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState({})
  const [error, setError] = useState('')
  useEffect(() => { request(`/jobs/${job.id}/review`).then(setData).catch(e => setError(e.message)) }, [job.id])
  if (!data) return <div className="panel"><p>{error || '加载掩码候选…'}</p></div>
  const approve = async () => {
    try { await request(`/jobs/${job.id}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(selected) }); onApproved() }
    catch (err) { setError(err.message) }
  }
  return <div className="panel review-panel"><div className="panel-title"><div><span className="eyebrow">HUMAN-IN-THE-LOOP</span><h2>选择最佳 SAM3 掩码</h2></div><button className="primary" onClick={approve}>批准并继续</button></div>
    {Object.entries(data.candidates).map(([asset, group]) => <div className="candidate-group" key={asset}><h3>{asset} <small>{group.prompt}</small></h3><div className="candidate-grid">
      {group.instances.map(item => <button key={item.instance} className={selected[asset] === item.instance ? 'candidate selected' : 'candidate'} onClick={() => setSelected({ ...selected, [asset]: item.instance })}>
        <img src={item.image_url} alt={`${asset} ${item.instance}`} /><span>#{item.instance} · {(item.score * 100).toFixed(1)}%</span>
      </button>)}
      {!group.instances.length && <p className="muted">没有超过阈值的候选，最终将使用已验证备用资产。</p>}
    </div></div>)}
    {error && <p className="error">{error}</p>}
  </div>
}

function LayoutEditor({ job, onSaved }) {
  const initial = job.config.layout || { landmarks: [
    { type: 'village', position: [29, 23], radius: 19 }, { type: 'bridge', position: [7, 0] },
    { type: 'watchtower', position: [42, 35] }, { type: 'stone_circle', position: [-43, 31] }
  ] }
  const [value, setValue] = useState(JSON.stringify(initial, null, 2)); const [message, setMessage] = useState('')
  const save = async () => {
    try { await request(`/jobs/${job.id}/layout`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: value }); setMessage('已保存；再次启动会从规划阶段重建。'); onSaved() }
    catch (err) { setMessage(err.message) }
  }
  return <div className="panel"><h2>布局参数</h2><p className="muted">坐标单位为米。修改后会让任务从世界规划阶段重新执行。</p><textarea className="code-editor" value={value} onChange={e => setValue(e.target.value)} /><div className="button-row"><button onClick={save}>保存布局</button><small>{message}</small></div></div>
}

function JobDetail({ job, refresh }) {
  const [artifacts, setArtifacts] = useState([]); const [quality, setQuality] = useState(null); const [logs, setLogs] = useState(''); const [tab, setTab] = useState('overview'); const [error, setError] = useState('')
  useEffect(() => { setArtifacts([]); setQuality(null) }, [job.id])
  useEffect(() => {
    let current = true
    request(`/jobs/${job.id}/artifacts`).then(value => { if (current) setArtifacts(value) }).catch(() => {})
    return () => { current = false }
  }, [job.id, job.updated_at])
  useEffect(() => {
    let current = true
    request(`/jobs/${job.id}/quality`).then(value => { if (current) setQuality(value) }).catch(() => { if (current) setQuality(null) })
    return () => { current = false }
  }, [job.id, job.updated_at])
  useEffect(() => {
    setLogs(''); const events = new EventSource(tokenizedUrl(`${API}/jobs/${job.id}/logs`, API_TOKEN))
    events.addEventListener('log', event => setLogs(old => (old + JSON.parse(event.data)).slice(-50000)))
    events.addEventListener('state', event => { const state = JSON.parse(event.data); if (state !== job.state) refresh() })
    return () => events.close()
  }, [job.id, job.state])
  const action = async (kind, body) => {
    try { setError(''); await request(`/jobs/${job.id}/${kind}`, { method: 'POST', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined }); refresh() }
    catch (err) { setError(err.message) }
  }
  const images = artifacts.filter(a => a.mime.startsWith('image/') && a.path.startsWith('world/') && !a.path.startsWith('world/orbit/'))
  const orbitFrames = artifacts.filter(a => a.mime.startsWith('image/') && a.path.startsWith('world/orbit/'))
  const glb = artifacts.find(a => a.path === 'world/world.glb') || artifacts.find(a => a.path === 'world/denver_airport_worldclaw_regional.glb')
  return <section className="job-detail">
    <div className="detail-head"><div><span className="eyebrow">JOB {job.id}</span><h1>{job.name}</h1><p>{workflowNames[job.workflow] || job.workflow} · {job.quality}</p></div><span className={`status ${job.state}`}>{stateNames[job.state] || job.state}</span></div>
    <div className="tabs"><button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>进度与结果</button><button className={tab === 'quality' ? 'active' : ''} onClick={() => setTab('quality')}>质量与对比</button>{!['denver_regional', 'template'].includes(job.workflow) && <button className={tab === 'layout' ? 'active' : ''} onClick={() => setTab('layout')}>布局</button>}<button className={tab === 'logs' ? 'active' : ''} onClick={() => setTab('logs')}>实时日志</button><button className={tab === 'files' ? 'active' : ''} onClick={() => setTab('files')}>产物</button></div>
    {job.state === 'awaiting_review' && job.workflow === 'full' && <ReviewPanel job={job} onApproved={refresh} />}
    {tab === 'overview' && <>
      <div className="panel"><div className="panel-title"><h2>生成流水线</h2><div className="button-row">
        {['created', 'interrupted'].includes(job.state) && <button className="primary small" onClick={() => action('start')}>启动</button>}
        {['running', 'queued'].includes(job.state) && <button className="danger small" onClick={() => action('cancel')}>停止</button>}
        {['failed', 'cancelled', 'interrupted'].includes(job.state) && <button className="small" onClick={() => action('retry')}>从断点重试</button>}
      </div></div><StageRail stages={job.stages} />{job.error && <p className="error">{job.error}</p>}{error && <p className="error">{error}</p>}</div>
      {images.length > 0 && <div className="panel"><h2>验证视图</h2><div className="gallery">{images.map(image => <a href={image.url} target="_blank" key={image.path}><img src={image.url} /><span>{image.path.split('/').pop()}</span></a>)}</div></div>}
      <ThreeViewer key={`${job.id}:${glb?.url || 'no-glb'}`} url={glb?.url} bytes={glb?.bytes} fallbackFrames={orbitFrames} posterUrl={images.find(image => image.path.endsWith('regional_delivery_hero.png'))?.url || images.find(image => image.path.endsWith('aerial_overview.png'))?.url || images[0]?.url} />
    </>}
    {tab === 'quality' && <QualityPanel quality={quality} images={images} artifacts={artifacts} job={job} onChanged={refresh} />}
    {tab === 'layout' && job.workflow !== 'template' && <LayoutEditor job={job} onSaved={refresh} />}
    {tab === 'logs' && <div className="panel"><h2>实时日志</h2><pre className="logs">{logs || '等待日志…'}</pre></div>}
    {tab === 'files' && <div className="panel"><h2>所有产物</h2><div className="file-list">{artifacts.map(file => <a href={file.url} download key={file.path}><span>{file.path}</span><small>{formatBytes(file.bytes)}</small></a>)}</div></div>}
  </section>
}

function App() {
  const selectedJobId = useRef(jobIdFromSearch(window.location.search)); const jobsRef = useRef([])
  const [jobs, setJobs] = useState([]); const [selected, setSelected] = useState(null); const [health, setHealth] = useState(null); const [defaults, setDefaults] = useState(null); const [catalog, setCatalog] = useState(null); const [newMode, setNewMode] = useState(!selectedJobId.current)
  const refresh = async () => {
    const list = await request('/jobs')
    jobsRef.current = list
    setJobs(list)
    const linkedJob = selectedJobId.current ? list.find(job => String(job.id) === selectedJobId.current) : null
    setSelected(linkedJob || null)
    if (linkedJob) setNewMode(false)
  }
  useEffect(() => { request('/health').then(setHealth); request('/defaults').then(setDefaults); request('/catalog').then(setCatalog).catch(() => {}); refresh() }, [])
  useEffect(() => { const timer = setInterval(refresh, 3000); return () => clearInterval(timer) }, [selected?.id])
  useEffect(() => {
    const restoreSelection = () => {
      const jobId = jobIdFromSearch(window.location.search)
      selectedJobId.current = jobId
      setSelected(jobId ? jobsRef.current.find(job => String(job.id) === jobId) || null : null)
      setNewMode(!jobId)
    }
    window.addEventListener('popstate', restoreSelection)
    return () => window.removeEventListener('popstate', restoreSelection)
  }, [])
  const active = useMemo(() => jobs.filter(j => ['running', 'queued', 'awaiting_review', 'contract_review'].includes(j.state)).length, [jobs])
  const updateUrl = jobId => {
    const nextPath = jobSelectionPath(window.location.href, jobId)
    const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`
    if (nextPath !== currentPath) window.history.pushState(window.history.state, '', nextPath)
  }
  const openJob = job => { selectedJobId.current = String(job.id); setSelected(job); setNewMode(false); updateUrl(job.id) }
  const openNewJob = () => { selectedJobId.current = null; setNewMode(true); setSelected(null); updateUrl(null) }
  return <div className="shell">
    <aside>
      <button className="brand" onClick={openNewJob}><span className="brand-mark">W</span><div><strong>WorldClaw</strong><small>STUDIO / LOCAL</small></div></button>
      <button className="new-button" onClick={openNewJob}>＋ 新建 3D 世界</button>
      <div className="sidebar-title"><span>任务</span><small>{active} 个活动</small></div>
      <nav>{jobs.map(job => <button key={job.id} onClick={() => openJob(job)} className={selected?.id === job.id ? 'active' : ''}><span className={`job-dot ${job.state}`} /><div><strong>{job.name}</strong><small>{stateNames[job.state]} · {job.quality}</small></div></button>)}</nav>
      <div className="system-card"><div><span className={`health-dot ${health?.status}`} /><strong>{health?.status === 'ready' ? '系统就绪' : '检查环境'}</strong></div><small>GPU {health?.gpu?.index ?? '…'} · {health?.gpu?.free_mib ? `${(health.gpu.free_mib / 1024).toFixed(1)} GiB 可用` : '遥测不可用'} · 单任务安全队列</small></div>
    </aside>
    <main>{newMode || !selected ? <NewJob defaults={defaults} catalog={catalog} onCreated={async id => { await refresh(); const job = await request(`/jobs/${id}`); openJob(job) }} /> : <JobDetail job={selected} refresh={refresh} />}</main>
  </div>
}

createRoot(document.getElementById('root')).render(<App />)
