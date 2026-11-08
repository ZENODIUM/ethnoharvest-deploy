#Remove all objects
rm(list=ls(all=TRUE))

#Load needed Packages
library(dplyr) 
library(corrplot)
library(ggplot2)
library(cowplot)
library(car)
library(MASS)
library(pscl)
library(sensemakr)
library(Hmisc)


#Data preparation####
#Select the data directory where you saved the data files: Skweness_Overview.csv,Shape_values_Overview.csv, Phenology_stages_2019_2023.csv and CS_values.csv.
data_dir <- choose.dir()

#Load competition and stress tolerating score data
CS <- read.table("CS_values.csv", sep=";",header=T ,fill=TRUE)

#Removal of lines with NAs for the competition score
CS <- CS %>% filter(C_score != "NA") 

#Calculate species' mean of competition and stress tolerating score
CS_mean <- CS %>% group_by(Species) %>% summarise(mean_C  =mean(C_score  ,na.rm=T),mean_S  =mean(S_score  ,na.rm=T))


#Load data of the curve characteristic: Maximum flowering intensity, Number of flowering peaks, Skweness)
skweness_data <-read.table(file.path(data_dir, "Skweness_Overview.csv"), sep=";",header=T ,fill=TRUE) #sep=";",dec = ".",
shape_data <-read.table(file.path(data_dir, "Shape_values_Overview.csv"), sep=";",header=T ,fill=TRUE) #sep=";",dec = ".",

#Merge the two datasets
data<-merge(skweness_data,shape_data, by=c("Ident"))

#Load Processed Phenology data: Flowering duration, Flowering Onset 
phen_proc <-read.table(file.path(data_dir, "Phenology_stages_2019_2023.csv"), sep=";",header=T ,fill=TRUE) #sep=";",dec = ".",

#Add an identifier with Species_ID and Year
phen_proc$Ident <-paste(phen_proc$Species_ID, phen_proc$Year, sep="_")

#Removal of species with flowering occurring almost all year round (FlDu>300, n=8)
phen_proc <- phen_proc %>% filter(FlDur<300)

#Merging datasets using Ident
data_merged<-merge(data,phen_proc, by=c("Ident"),all=T)


#Selecting and renaming relevant columns
data_merged<-data_merged%>%dplyr::select(Species_ID.x,Ident,Species.x,Botanic_Garden.x,Year.x,skewness,max_flowering_intensity,number_peaks,FlOn,FlDur)
data_merged<-data_merged %>% rename(Botanic_Garden = Botanic_Garden.x)
data_merged<-data_merged %>% rename(Species_ID = Species_ID.x)
data_merged<-data_merged %>% rename(Species = Species.x)

#Removing of rows with skewness = NA
skweness_data_merged <- data_merged[!(is.na(data_merged$skewness)), ]
#Selecting rows with one or more flowering peaks
skweness_data_merged <- skweness_data_merged %>% filter(number_peaks > 0) 
#Setting skewness as NA for all rows with more than one flowering peak
skweness_data_merged$skewness[skweness_data_merged$number_peaks > 1] <- NA


#Calculating mean values per garden: Number of flowering peaks, Maximum flowering intensity, Flowering duration,Skweness, and Flowering onset
Species_ID_mean <- skweness_data_merged %>% group_by(Species_ID) %>% summarise(Species = first(Species), mean_peaks  =mean(number_peaks,na.rm=T), mean_max_intensity=mean(max_flowering_intensity,na.rm=T),FlDur=mean(FlDur,na.rm=T), mean_skewness=mean(skewness, na.rm=T),FlOn=mean(FlOn, na.rm=T))

#Calculating mean values per species
data_final <- Species_ID_mean %>% group_by(Species) %>% summarise(mean_skewness=mean(mean_skewness, na.rm=T),FlOn=mean(FlOn, na.rm=T) ,FlDur=mean(FlDur,na.rm=T),mean_high  =mean(mean_peaks,na.rm=T), mean_max_intensity=mean(mean_max_intensity,na.rm=T))

#Adding strees tolerating and competition score
data_final<-merge(data_final,CS_mean, by=c("Species"))

#Save for later use
data_per_species<-data_final

############################################################################################################
#Analyses on species level across all gardens and years####
#Number of Flowering peaks####

#Define each species of the data set, whether it has one or more than one flowering peak, and set this property as a factor.
one_peak <- data_final %>% filter(mean_high==1 )
one_peak$number_peaks <- "=1"

more_than_one_peak <- data_final %>% filter(mean_high>1) 
more_than_one_peak$number_peaks <- "higher1"

data_h<-rbind(one_peak,more_than_one_peak)
data_h$number_peaks <- as.factor(data_h$number_peaks)


#Stress tolerance
#Binonminal generalised model with strees tolerating score as explanatory variable
model <- glm(number_peaks ~ mean_S, data = data_h, family = binomial)

#Summary of the modeloutput
summary(model)

#Calculation of the pseudo-R2
pR2(model)

#Predicting probabilities of the binomial generalised linear model (GLM)
data_h$predicted <- predict(model, type = "response")

#Graph
Fig2a<-ggplot(data_h, aes(x = mean_S, y = as.numeric(number_peaks) - 1)) +
  geom_point(alpha = 0.5) +  # echte Datenpunkte
  geom_line(aes(y = predicted), color = "black", size = 1) +
  labs(x = "Stress tolerance [%]", y = "Probability of more than one flowering peak") +
  theme_classic() +
  theme(axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_text(size = 20),axis.title.x = element_text(size = 20))+
  geom_text(x=50, y=0.75, label=expression("Pseudo R"^2 == 0.02), size=8,parse = TRUE)


#Competitiveness
#Binonminal generalised model with strees tolerating score as explanatory variable
model <- glm(number_peaks ~ mean_C, data = data_h, family = binomial)

#Summary of the modeloutput
summary(model)

#Calculation of the pseudo-R2
pR2(model)

#Predicting probabilities of the binomial generalised linear model (GLM)
data_h$predicted <- predict(model, type = "response")

#Graph
Fig2b<-ggplot(data_h, aes(x = mean_C, y = as.numeric(number_peaks) - 1)) +
  geom_point(alpha = 0.5) +  # echte Datenpunkte
  geom_line(aes(y = predicted), color = "black", size = 1) +  # logistische Regressionskurve
  labs(x = "Competitiveness [%]", y = "") +
  theme_classic() +
  theme(axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_text(size = 20),axis.title.x = element_text(size = 20))+
  geom_text(x=50, y=0.75, label=expression("Pseudo R"^2 == 0.06), size=8,parse = TRUE)

#Phenological niche 
#Binonminal generalised model with strees tolerating score as explanatory variable
model <- glm(number_peaks ~ FlOn, data = data_h, family = binomial)

#Summary of the modeloutput
summary(model)

#Calculation of the pseudo-R2
pR2(model)

#Predicting probabilities of the binomial generalised linear model (GLM)
data_h$predicted <- predict(model, type = "response")

#Graph
Fig2c<-ggplot(data_h, aes(x = FlOn, y = as.numeric(number_peaks) - 1)) +
  geom_point(alpha = 0.5) +  # echte Datenpunkte
  geom_line(aes(y = predicted), color = "black", size = 1) +  # logistische Regressionskurve
  labs(x = "Flowering onset [DOY]", y = "") +
  theme_classic() +
  theme(axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_text(size = 20),axis.title.x = element_text(size = 20))+
  geom_text(x=150, y=0.75, label=expression("Pseudo R"^2 == 0.02), size=8,parse = TRUE)


#Mean Maximum Flowering intensity####

#Including Flowering onset as quadratic predictor
data_final$FlOn2 <- data_final$FlOn^2

#Linear model with Maximum flowering intensity as response variable
m1<-lm(mean_max_intensity~FlOn+FlOn2+mean_S+mean_C,data=data_final)

#Extracting F- and p-value
Anova(m1, type = 2)

#Extracting R2
summary(m1)

#Checking normal distribution of the residuals
qqnorm(resid(m1))
qqline(resid(m1))

#Testing variance inflation
vif(m1)

#Extracting partial R2
partial_r2(m1)

#Graph with Flowering Onset as explanatory variable

Fig4a<-ggplot(data_final,aes(x=FlOn,y=mean_max_intensity))+geom_point() +
    stat_smooth(method = "lm",formula = y ~ poly(x, 2), se = T,linetype = "solid", color = "black",size=1.3)+
    theme_classic()+
    scale_y_continuous(expand = c(0, 0),breaks=c(0,20,40,60,80,100),limits=c(0,104))+
    scale_x_continuous(expand = c(0, 0),breaks=c(0,50,100,150,200,250),limits=c(0, 280))+
    theme(axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_text(size = 21),axis.title.x = element_text(size = 21),axis.ticks.x = element_line(size = 1),axis.ticks.y = element_line(size = 1))+
    labs(y="Maximal flowering intensity [%]", x="Flowering onset [DOY]")+
    geom_text(x=40, y=20, label="R^2==0.11", size=10,parse = TRUE)


#Flowering duration####
#Including Flowering onset as quadratic predictor
data_final$FlOn2 <- data_final$FlOn^2

#Linear model with Maximum flowering intensity as response variable
m1<-lm(FlDur~FlOn+FlOn2+mean_S+mean_C,data=data_final)

#Extracting F- and p-value
Anova(m1, type = 2)

#Extracting R2
summary(m1)

#Checking normal distribution of the residuals
qqnorm(resid(m1))
qqline(resid(m1))

#Testing variance inflation
vif(m1)

#Extracting partial R2
partial_r2(m1)

#Graph with competition score as explanatory variable
Fig3a<-ggplot(data_final,aes(x=mean_C, y=FlDur))+geom_point(size=1.3)+
  theme_classic()+
  geom_smooth(method="lm",size=1.3,color="black",linetype = "solid")+
  scale_x_continuous(expand = c(0, 0),breaks=c(0,25,50,75,100),limits=c(-1, 107))+
  theme(legend.position ="none", axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_text(size = 20),axis.title.x = element_blank(),axis.ticks.x = element_line(size = 1),axis.ticks.y = element_line(size = 1))+
  labs(x="Competitiveness [%]", y="Flowering duration [Days]")+
  geom_text(x=80, y=160, label="R^2==0.06", size=10,parse = TRUE)



#Skewness - Only for species with one flowering peak####

##Including Flowering onset as quadratic predictor
one_peak$FlOn2 <- one_peak$FlOn^2

#Linear model with Maximum flowering intensity as response variable
m1<-lm(mean_skewness~FlOn+FlOn2+mean_S+mean_C,data=one_peak)

#Extracting F- and p-value
Anova(m1, type = 2)

#Extracting R2
summary(m1)

#Checking normal distribution of the residuals
qqnorm(resid(m1))
qqline(resid(m1))

#Testing variance inflation
vif(m1)

#Extracting partial R2
partial_r2(m1)

#Graph with competition score as explanatory variable

Fig3c<-ggplot(data_final,aes(x=mean_C, y=mean_skewness))+geom_point(size=1.3)+
  theme_classic()+
  geom_smooth(method="lm",size=1.3,color="black",linetype = "solid")+
  scale_x_continuous(expand = c(0, 0),breaks=c(0,25,50,75,100),limits=c(-1, 107))+
  theme(legend.position ="none", axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_text(size = 21),axis.title.x = element_text(size = 21),axis.ticks.x = element_line(size = 1),axis.ticks.y = element_line(size = 1))+
  labs(x="Competitiveness [%]", y="Skewness")+
  geom_text(x=20, y=-1.5, label="R^2==0.07", size=10,parse = TRUE)

  



############################################################################################################
#Analyse on accession level across all gardens####
#Using accession specific means per species of Maximum flowering intensity ~ Flowerin Onset, Flowering duration ~ C_Score, Skweness~C_Score
#Only considering associations which were significant on species level

#Extracting Garden name per Species_ID
garden<- data_merged[,c(1,4)]
garden <- garden %>% distinct()

#Adding Garden names to Species_ID_mean
Species_ID_mean<-merge(Species_ID_mean,garden, by=c("Species_ID"))

#Adding stress tolerating and competition score
data_final<-merge(Species_ID_mean,CS, by=c("Species_ID"))

#Removing of rows with C_score = NaN
data_final <- data_final %>% filter(C_score != "NaN") 

#Check how many species per garden have values for stress tolerating and competition score
n_sample <- data_final  %>% group_by(Botanic_Garden) %>% summarise(n_samples =length(C_score))

#Only selecting botanic gardens with more that 30 species (i.e. deleting Tuebingen, Srinagar, Trondheim and Xixon)
data_final<-merge(data_final,n_sample, by=c("Botanic_Garden"))
data_final <- data_final %>% filter(n_samples > 30)


#Colour scheme for the respective gardens
garden_colors <- c("Berlin"="#7fc97f","Frankfurt"="#beaed4","Halle"="#fdc086","Jena"="yellow","Leipzig"="#386cb0","Potsdam"="#f0027f","Vienna"="#bf5b17")



#Maximum flowering intensity ~ Flowering Onset####

#Including Flowering onset as quadratic predictor
data_final$FlOn2 <- data_final$FlOn^2

#Most complex model with interactions
m1 <- lm(mean_max_intensity ~ FlOn*Botanic_Garden+Botanic_Garden*FlOn2, data = data_final)

#Stepwise model simplification finding the best model
best_model <- stepAIC(m1, direction = "backward")

#Extracting F- and p-value
Anova(best_model, type = 3)

#Extracting R2
summary(best_model)

#Checking normal distribution of the residuals
qqnorm(resid(best_model))
qqline(resid(best_model))

#Testing variance inflation
vif(best_model)

#Extracting partial R2
partial_r2(best_model)


#Graph
Fig4b<-ggplot(data_final, aes(x = FlOn, y = mean_max_intensity,color=Botanic_Garden, fill=Botanic_Garden))+theme_classic()+
    geom_point(shape = 21, size = 2, color = "black", stroke = 1) +
    stat_smooth(aes(color = Botanic_Garden),method = "lm",formula = y ~ poly(x, 2), se = F,size=1.3)+
    scale_fill_manual(values=garden_colors) +  # Farben basierend auf Temperaturen
    scale_color_manual(values=garden_colors) +  # Farben basierend auf Temperaturen
    labs(x = "Flowering onset [DOY]",y = "Maximal flowering intensity [%]")+
    theme(title = element_text(size=19),legend.position =c(0.85,0.30),legend.title = element_blank(),legend.text=element_text(size=19),axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_blank(),axis.title.x = element_text(size = 21),axis.ticks.x = element_line(size = 1),axis.ticks.y = element_line(size = 1))+
    scale_x_continuous(expand = c(0, 0),breaks=c(0,50,100,150,200,250),limits=c(0,275))+
    scale_y_continuous(expand = c(0, 0),breaks=c(0,20,40,60,80,100),limits=c(0,104))+
    geom_text(x=40, y=15, label=expression("R"^2==0.27), size=10,color = "black")+
    guides(fill = guide_legend(override.aes = list(size = 4)),  # Legendenpunkt größer
         color = guide_legend(override.aes = list(size = 4)))  # Falls color auch in der Legende


  

#Flowering duration####

#Data transformation of flowering duration
data_final$FlDur_trans <-sqrt(data_final$FlDur)

#Most complex model with interactions
m1 <- lm(FlDur_trans ~ C_score*Botanic_Garden, data = data_final)

#Stepwise model simplification finding the best model
best_model <- stepAIC(m1, direction = "backward")

#Extracting F- and p-value
Anova(best_model, type = 3)

#Extracting R2
summary(best_model)

#Checking normal distribution of the residuals
qqnorm(resid(best_model))
qqline(resid(best_model))

#Testing variance inflation
vif(best_model)

#Extracting partial R2
partial_r2(best_model)

#Graph
Fig3b<-ggplot(data_final, aes(x = C_score, y = FlDur, color=Botanic_Garden, fill=Botanic_Garden))+theme_classic()+
  geom_point(shape = 21, size = 2, color = "black", stroke = 1) +
  geom_smooth(aes(color = Botanic_Garden),method = "lm", se = F, linetype="solid",size=1.3)+
  scale_fill_manual(values=garden_colors) +  # Farben basierend auf Temperaturen
  scale_color_manual(values=garden_colors) +  # Farben basierend auf Temperaturen
  labs(x = "Competitiveness [%]",y = "Flowering duration [Days]")+
  theme(title = element_text(size=19),legend.position =c(0.8,0.75),legend.title = element_blank(),legend.text=element_text(size=19),axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_blank(),axis.title.x = element_blank(),axis.ticks.x = element_line(size = 1),axis.ticks.y = element_line(size = 1))+
  scale_x_continuous(expand = c(0, 0),breaks=c(0,25,50,75,100),limits=c(-1,103))+
  geom_text(x=25, y=192, label=expression("R"^2==0.12), size=10,color = "black")+
  guides(fill = guide_legend(override.aes = list(size = 4)),  # Legendenpunkt größer
         color = guide_legend(override.aes = list(size = 4)))  # Falls color auch in der Legende


#Skewness####

#Most complex model with interactions
m1 <- lm(mean_skewness ~ C_score*Botanic_Garden, data = data_final)

#Stepwise model simplification finding the best model
best_model <- stepAIC(m1, direction = "backward")

#Extracting F- and p-value
Anova(best_model, type = 3)

#Extracting R2
summary(best_model)

#Checking normal distribution of the residuals
qqnorm(resid(best_model))
qqline(resid(best_model))

#Testing variance inflation
vif(best_model)

#Extracting partial R2
partial_r2(best_model)

#Graph
Fig3d<-ggplot(data_final, aes(x = C_score, y = mean_skewness, color=Botanic_Garden, fill=Botanic_Garden))+theme_classic()+
  geom_point(shape = 21, size = 2 , color = "black", stroke = 1) +
  geom_smooth(aes(color = Botanic_Garden),method = "lm", se = F, linetype="solid",size=1.3)+
  scale_fill_manual(values=garden_colors) +  # Farben basierend auf Temperaturen
  scale_color_manual(values=garden_colors) +  # Farben basierend auf Temperaturen
  labs(x = "Competitiveness [%]",y = "Skewness")+
  theme(title = element_text(size=19),legend.position ="none",legend.title = element_blank(),legend.text=element_text(size=19),axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_blank(),axis.title.x = element_text(size = 21),axis.ticks.x = element_line(size = 1),axis.ticks.y = element_line(size = 1))+
  scale_x_continuous(expand = c(0, 0),breaks=c(0,25,50,75,100),limits=c(-1,103))+
  geom_text(x=80, y=4, label=expression("R"^2==0.10), size=10,color = "black")



######################################################################################################
###Graphs-Final#######################################################################################

#Figure 2
ppi<-300 # set resolution
jpeg(file="Figure2_Binominal_Highpoints.jpeg", height=7*ppi, width=16*ppi, res=ppi)

plot_grid(Fig2a,Fig2b,Fig2c,nrow = 1,ncol = 3,label_size = 20,labels = c("a)","b)","c)"), align="hv")

dev.off()

#Figure 3
ppi<-300 # set resolution
jpeg(file="Figure3_Competiveness.jpeg", height=10*ppi, width=16*ppi, res=ppi)

plot_grid(Fig3a,Fig3b,Fig3c,Fig3d,nrow = 2,ncol = 2,label_size = 20,labels = c("a)","b)","c)","d)"), align="hv")

dev.off()


#Figure 4
ppi<-300 # set resolution
jpeg(file="Figure4_FloweringOnset_Curves.jpeg", height=7*ppi, width=16*ppi, res=ppi)

plot_grid(Fig4a, Fig4b,nrow = 1,ncol = 2,label_size = 20,labels = c("a)","b)"), align="hv")

dev.off()




####################################################################################################









#Supplemental material#######

#Table S1####
#Information of alle used data on species level
#Extract information for number of flowering peaks
data_h1 <- data_h[,c(1,9)]
#Extract information for Maximum flowering intensity,Flowering Duration, Skweness, Phenological niche, competition and stress tolerating score
data_perSpecies1<-merge(data_per_species,data_h1, by=c("Species"))

#Extract information on number of considered flowering curves per species
overview_allcurves<-merge(skweness_data_merged,CS_mean, by=c("Species"))
number_curves <- overview_allcurves %>% group_by(Species) %>% summarise(number_curves=length(Species_ID))

#Extract information on number of considered measurements of competition and stress tolerating score per species
number_CS <- CS %>% group_by(Species) %>% summarise(number_CS=length(Species_ID))

#Merge datasets
data_perSpecies1<-merge(data_perSpecies1,number_curves,by=c("Species"))
data_perSpecies1<-merge(data_perSpecies1,number_CS,by=c("Species"))

#Specification that the skewness is set to NA if the species was set as more than one peak
data_perSpecies1$mean_skewness[data_perSpecies1$Highpoints =="higher1"] <- NA

#Reorder the colums
data_perSpecies1 <- data_perSpecies1 %>% dplyr::select(Species, number_peaks, mean_max_intensity, FlDur,mean_skewness, mean_C, mean_S, FlOn,number_curves, number_CS)

#Saving the data set
write.table(data_perSpecies1, file = file.path(data_dir, "TableS1.csv"), sep=";",dec = ".", row.names = FALSE)



#Fig S2####
#Histogramm Flowering intensity
g1<-ggplot(data_perSpecies1,aes(x=mean_max))+geom_histogram(bins=22,alpha = 1,color="black")+
  theme_classic()+
  scale_x_continuous(expand = c(0, 0),breaks=c(0,20,40,60,80,100),limits=c(-1, 105))+
  theme(legend.position ="none", axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_text(size = 21),axis.title.x = element_text(size = 21),axis.ticks.x = element_line(size = 1),axis.ticks.y = element_line(size = 1))+
  labs(x="Species' mean maximal flowering intensity [%]", y="Number of species")


ppi<-300 # set resolution
jpeg(file="FigureS2_Histograms_Flowering intensity.jpeg", height=8*ppi, width=13*ppi, res=ppi)

g1
dev.off()

#Fig S3####
#Histogramm Flowering duration

g1<-ggplot(data_perSpecies1,aes(x=FlDur))+geom_histogram(bins=30,alpha = 1,color="black")+
  theme_classic()+
  scale_x_continuous(expand = c(0, 0),breaks=c(0,50,100,150,200),limits=c(-1, 210))+
  theme(legend.position ="none", axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_text(size = 21),axis.title.x = element_text(size = 21),axis.ticks.x = element_line(size = 1),axis.ticks.y = element_line(size = 1))+
  labs(x="Species' mean flowering duration [Days]", y="Number of species")


ppi<-300 # set resolution
jpeg(file="FigureS3_Histograms_Flowering duration.jpeg", height=8*ppi, width=13*ppi, res=ppi)

g1
dev.off()

#Fig S4####
#Histogramm Skewness
g1<-ggplot(data_perSpecies1,aes(x=mean_skewness))+geom_histogram(bins=40,alpha = 1,color="black")+
  theme_classic()+
  scale_x_continuous(expand = c(0, 0),breaks=c(-2,0,2,4),limits=c(-2.2, 5))+
  theme(legend.position ="none", axis.text.x = element_text(size = 19),axis.text.y = element_text(size = 19),axis.title.y = element_text(size = 21),axis.title.x = element_text(size = 21),axis.ticks.x = element_line(size = 1),axis.ticks.y = element_line(size = 1))+
  labs(x="Species' mean skewness", y="Number of species")


ppi<-300 # set resolution
jpeg(file="FigureS4_Histograms_Skewness.jpeg", height=8*ppi, width=13*ppi, res=ppi)

g1
dev.off()



#Fig S5####

filtered_data <- data_perSpecies1 %>% dplyr::filter(number_peaks == "=1") %>% dplyr::select(mean_skewness, mean_max_intensity, FlDur)

data_cor<-filtered_data %>% rename("Max. flowering intensity" = mean_max_intensity, "Flowering duration"=FlDur,"Skewness"=mean_skewness)

data_cor <- data_cor %>% mutate_all(~ifelse(is.nan(.), NA, .))
data_cor<-as.matrix(data_cor)

res<-rcorr(data_cor,type=c("spearman"))

ppi<-300 # set resolution
jpeg(file="FigureS6_CorrelationMatrix.jpeg", height=5*ppi, width=10*ppi, res=ppi)

corrplot(res$r, type = "upper", diag=F,order = "original",cl.cex=1.2,cl.ratio=0.6, tl.cex=1.2,tl.col = "black", tl.srt = 45, insig="p-value")

dev.off()



