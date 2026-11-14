import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.serialization")
    id("com.chaquo.python")
}

val packagePins: List<String> = rootProject.file("packages.txt")
    .readLines()
    .map { it.trim() }
    .filter { it.isNotEmpty() && !it.startsWith("#") }

fun resolveBuildPython(): String? {
    System.getenv("PYRUNNER_BUILD_PYTHON")?.takeIf { it.isNotBlank() }?.let { return it }
    val properties = Properties()
    val local = rootProject.file("local.properties")
    if (local.exists()) {
        local.inputStream().use { properties.load(it) }
    }
    return properties.getProperty("build.python")?.takeIf { it.isNotBlank() }
}

val syncSharedUi = tasks.register<Copy>("syncSharedUi") {
    from(rootProject.file("../ui")) {
        include("index.html")
        include("css/**")
        include("js/**")
        include("vendor/**")
    }
    into(layout.projectDirectory.dir("src/main/assets/web"))
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
}

val syncRuntime = tasks.register<Copy>("syncRuntime") {
    from(rootProject.file("../runtime/pyrunner_rt"))
    into(layout.projectDirectory.dir("src/main/python/pyrunner_rt"))
    include("**/*.py")
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
}

val syncExamples = tasks.register<Copy>("syncExamples") {
    from(rootProject.file("../examples"))
    into(layout.projectDirectory.dir("src/main/assets/examples"))
    include("*.py")
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
}

val syncPackages = tasks.register<Copy>("syncPackages") {
    from(rootProject.file("packages.txt"))
    into(layout.projectDirectory.dir("src/main/assets"))
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
}

val syncShared = listOf(syncSharedUi, syncRuntime, syncExamples, syncPackages)

android {
    namespace = "com.pyrunner.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.pyrunner.app"
        minSdk = 24
        targetSdk = 35
        versionCode = 8
        versionName = "0.1.7"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        val python = resolveBuildPython()
        if (python != null) {
            buildPython(python)
        }
        pip {
            packagePins.forEach { install(it) }
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.2")
    implementation("androidx.documentfile:documentfile:1.0.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    testImplementation("junit:junit:4.13.2")
}

afterEvaluate {
    tasks.named("preBuild").configure { dependsOn(syncShared) }
    tasks.matching { task ->
        val name = task.name
        name.contains("Python", ignoreCase = true) ||
            (name.contains("merge", ignoreCase = true) && name.contains("Assets", ignoreCase = true))
    }.configureEach {
        dependsOn(syncShared)
    }
}
